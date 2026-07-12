"""``sevn completion`` install/show/uninstall (`specs/23-cli.md` §2.8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_completion_show_bash(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["completion", "show", "bash"])
    assert result.exit_code == 0
    assert "complete" in result.stdout
    assert "sevn" in result.stdout


def test_completion_install_uninstall_round_trip_zsh(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")

    install = runner.invoke(get_command(app), ["completion", "install", "zsh"])
    assert install.exit_code == 0
    zfunc = home / ".zfunc" / "_sevn"
    assert zfunc.is_file()
    assert "compdef" in zfunc.read_text(encoding="utf-8")

    again = runner.invoke(get_command(app), ["completion", "install", "zsh"])
    assert again.exit_code == 0

    uninstall = runner.invoke(get_command(app), ["completion", "uninstall", "zsh"])
    assert uninstall.exit_code == 0
    assert not zfunc.is_file()

    uninstall_again = runner.invoke(get_command(app), ["completion", "uninstall", "zsh"])
    assert uninstall_again.exit_code == 0


def test_completion_invalid_shell_exit2(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["completion", "install", "powershell"])
    assert result.exit_code == 2


def test_completion_install_json_failure_shape(runner: ClickCliRunner) -> None:
    result = runner.invoke(
        get_command(app),
        ["completion", "install", "nope", "--json"],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is False
    assert payload["error_code"] == "USAGE"
    assert payload["exit_code"] == 2
