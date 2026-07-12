"""Tests for ``sevn gh`` GitHub integration helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import typer
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.commands.gh_cmd import GITHUB_TOKEN_CREATE_URL
from sevn.proxy.integration.github import GITHUB_TOKEN_SECRET


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_gh_help_shows_explanation_and_github_link(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["gh", "--help"])
    assert result.exit_code == 0
    assert "GitHub integration helpers" in result.stdout
    assert GITHUB_TOKEN_CREATE_URL in result.stdout
    assert "add-github-token" in result.stdout
    assert GITHUB_TOKEN_SECRET in result.stdout


def test_gh_without_subcommand_shows_intro_and_help(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["gh"])
    assert result.exit_code == 0
    assert GITHUB_TOKEN_CREATE_URL in result.stdout
    assert "add-github-token" in result.stdout


def test_gh_add_github_token_delegates_to_secrets_put(runner: ClickCliRunner) -> None:
    with patch("sevn.cli.commands.gh_cmd.execute_secrets_put") as put:
        result = runner.invoke(
            get_command(app),
            ["gh", "add-github-token", "--value", "ghp_test_token"],
        )
    assert result.exit_code == 0
    put.assert_called_once_with(
        alias=GITHUB_TOKEN_SECRET,
        command="sevn gh add-github-token",
        value="ghp_test_token",
        stdin=False,
        confirm_fingerprint=None,
        json_out=False,
        stdin_prompt="GitHub token: ",
    )


def test_gh_add_github_token_stdin_shows_setup_guide(runner: ClickCliRunner) -> None:
    with patch("sevn.cli.commands.gh_cmd.execute_secrets_put") as put:
        put.side_effect = typer.Exit(0)
        result = runner.invoke(
            get_command(app),
            ["gh", "add-github-token", "--stdin"],
            input="ghp_test\n",
        )
    assert result.exit_code == 0
    assert GITHUB_TOKEN_CREATE_URL in result.stdout
    assert "Scopes" in result.stdout
    put.assert_called_once()
