"""Tests for ``sevn openwiki`` CLI helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import typer
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.skills.openwiki_secrets import OPENWIKI_LLM_API_KEY_SECRET


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_openwiki_help_shows_install_and_configure(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["openwiki", "--help"])
    assert result.exit_code == 0
    assert "openwiki install" in result.stdout
    assert "openwiki configure" in result.stdout
    assert OPENWIKI_LLM_API_KEY_SECRET in result.stdout


def test_openwiki_without_subcommand_shows_intro(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["openwiki"])
    assert result.exit_code == 0
    assert "sevn openwiki install" in result.stdout


def test_openwiki_install_delegates_to_install_helper(runner: ClickCliRunner) -> None:
    with patch(
        "sevn.cli.commands.openwiki_cmd.run_openwiki_install",
        return_value=(0, "openwiki CLI already on PATH"),
    ) as install:
        result = runner.invoke(get_command(app), ["openwiki", "install"])
    assert result.exit_code == 0
    install.assert_called_once_with(skip_if_installed=True)
    assert "already on PATH" in result.stdout


def test_openwiki_configure_delegates_to_secrets_put(runner: ClickCliRunner) -> None:
    with patch("sevn.cli.commands.openwiki_cmd.execute_secrets_put") as put:
        result = runner.invoke(
            get_command(app),
            ["openwiki", "configure", "--value", "sk-openwiki-test"],
        )
    assert result.exit_code == 0
    put.assert_called_once_with(
        alias=OPENWIKI_LLM_API_KEY_SECRET,
        command="sevn openwiki configure",
        value="sk-openwiki-test",
        stdin=False,
        confirm_fingerprint=None,
        json_out=False,
        stdin_prompt="OpenWiki LLM API key: ",
    )


def test_openwiki_setup_success_when_secrets_put_exits_zero(runner: ClickCliRunner) -> None:
    with (
        patch(
            "sevn.cli.commands.openwiki_cmd.run_openwiki_install",
            return_value=(0, "installed"),
        ) as install,
        patch("sevn.cli.commands.openwiki_cmd.execute_secrets_put") as put,
    ):
        put.side_effect = typer.Exit(0)
        result = runner.invoke(
            get_command(app),
            ["openwiki", "setup", "--stdin"],
            input="sk-openwiki\n",
        )
    assert result.exit_code == 0
    install.assert_called_once_with(skip_if_installed=True)
    put.assert_called_once()
    assert put.call_args.kwargs["json_out"] is False
    assert "stored integration.openwiki.llm_api_key" in result.stdout
    assert "configure failed" not in result.stdout.lower()


def test_openwiki_setup_json_emits_single_envelope(runner: ClickCliRunner) -> None:
    import json

    with (
        patch(
            "sevn.cli.commands.openwiki_cmd.run_openwiki_install",
            return_value=(0, "installed"),
        ),
        patch("sevn.cli.commands.openwiki_cmd.execute_secrets_put") as put,
    ):
        put.side_effect = typer.Exit(0)
        result = runner.invoke(
            get_command(app),
            ["openwiki", "setup", "--stdin", "--json"],
            input="sk-openwiki\n",
        )
    assert result.exit_code == 0
    assert put.call_args.kwargs["json_out"] is False
    docs = [json.loads(line) for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(docs) == 1
    assert docs[0]["command"] == "sevn openwiki setup"
    assert docs[0]["configure"]["ok"] is True
