"""Tests for ``execute_secrets_put`` stdin handling."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
import typer
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.commands.secrets_cmd import execute_secrets_put


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_execute_secrets_put_stdin_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdin", StringIO("ghp_piped\n"))
    with (
        patch("sevn.cli.commands.secrets_cmd.secrets_put") as put,
        patch(
            "sevn.cli.commands.secrets_cmd.load_bound_workspace",
        ) as load_bw,
    ):
        put.return_value = {
            "alias": "integration.github.token",
            "fingerprint_sha256_hex": "ab",
            "overwritten": False,
        }
        with pytest.raises(typer.Exit) as exc:
            execute_secrets_put(
                alias="integration.github.token",
                command="sevn gh add-github-token",
                value=None,
                stdin=True,
                confirm_fingerprint=None,
                json_out=False,
                stdin_prompt="GitHub token: ",
            )
    assert exc.value.exit_code == 0
    put.assert_called_once()
    assert put.call_args.kwargs["plaintext"] == "ghp_piped"
    load_bw.assert_called_once()


def test_execute_secrets_put_stdin_tty_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with (
        patch("sevn.cli.commands.secrets_cmd.getpass.getpass", return_value="ghp_tty") as gp,
        patch(
            "sevn.cli.commands.secrets_cmd.secrets_put",
        ) as put,
        patch("sevn.cli.commands.secrets_cmd.load_bound_workspace"),
    ):
        put.return_value = {
            "alias": "k",
            "fingerprint_sha256_hex": "ab",
            "overwritten": False,
        }
        with pytest.raises(typer.Exit) as exc:
            execute_secrets_put(
                alias="k",
                command="sevn gh add-github-token",
                value=None,
                stdin=True,
                confirm_fingerprint=None,
                json_out=False,
                stdin_prompt="GitHub token: ",
            )
    assert exc.value.exit_code == 0
    gp.assert_called_once_with("GitHub token: ")
    put.assert_called_once()
    assert put.call_args.kwargs["plaintext"] == "ghp_tty"


def test_gh_add_github_token_stdin_pipe(runner: ClickCliRunner) -> None:
    with patch("sevn.cli.commands.gh_cmd.execute_secrets_put") as put:
        put.side_effect = typer.Exit(0)
        result = runner.invoke(
            get_command(app),
            ["gh", "add-github-token", "--stdin"],
            input="ghp_piped\n",
        )
    assert result.exit_code == 0
    put.assert_called_once()
    assert put.call_args.kwargs["stdin"] is True
