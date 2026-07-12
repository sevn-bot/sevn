"""Tests for installable shell-history hooks."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.shell_history import STORE_PASSPHRASE_HISTORY_MARKER, scrub_shell_history
from sevn.cli.shell_history_hooks import (
    SHELL_HISTORY_HOOK_BEGIN,
    ensure_shell_history_hook,
    install_shell_history_hook,
    shell_history_hook_installed,
    uninstall_shell_history_hook,
)


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_install_and_uninstall_zsh_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("HOME", td)
        rc = install_shell_history_hook(shell="zsh")
        assert rc == Path(td) / ".zshrc"
        assert shell_history_hook_installed(shell="zsh")
        text = rc.read_text(encoding="utf-8")
        assert SHELL_HISTORY_HOOK_BEGIN in text
        assert "__sevn_is_secret_cmd" in text
        assert "sevn secrets put" in text
        assert "fc -R" not in text
        assert uninstall_shell_history_hook(shell="zsh")
        assert not shell_history_hook_installed(shell="zsh")


def test_shell_history_install_cli(runner: ClickCliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("HOME", td)
        monkeypatch.setenv("SHELL", "/bin/zsh")
        result = runner.invoke(get_command(app), ["shell-history", "install", "zsh"])
        assert result.exit_code == 0
        assert "installed zsh shell-history hook" in result.stdout
        assert shell_history_hook_installed(shell="zsh")


def test_ensure_shell_history_hook_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("HOME", td)
        monkeypatch.setenv("SHELL", "/bin/zsh")
        first = ensure_shell_history_hook(shell="zsh")
        second = ensure_shell_history_hook(shell="zsh")
        assert first is not None
        assert second is None


def test_scrub_shell_history_with_explicit_path(tmp_path: Path) -> None:
    hist = tmp_path / "hist"
    hist.write_text(
        ": 1:0;keep\n: 2:0;sevn secrets store-passphrase --stdin\n",
        encoding="utf-8",
    )
    removed = scrub_shell_history(
        containing=STORE_PASSPHRASE_HISTORY_MARKER,
        histfile_path=hist,
    )
    assert removed == 1
    assert STORE_PASSPHRASE_HISTORY_MARKER not in hist.read_text(encoding="utf-8")
