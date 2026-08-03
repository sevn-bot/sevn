"""Batch C W13 — ``sevn capabilities`` CLI (#151)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app

_VALID_STATUSES = frozenset({"implemented", "stub", "unavailable"})


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_capabilities_cli_exit_zero_lists_channels(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["capabilities"])
    assert result.exit_code == 0, result.output
    assert "capabilities:" in result.output
    assert "telegram" in result.output
    assert "implemented" in result.output
    assert "signal" in result.output
    assert "stub" in result.output


def test_capabilities_cli_json_emits_channel_inventory(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["capabilities", "--json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    channels = body.get("channels")
    assert isinstance(channels, list)
    assert len(channels) >= 2
    assert isinstance(body.get("generated_at"), int)
    for row in channels:
        assert row.get("status") in _VALID_STATUSES
        name = row.get("name")
        assert isinstance(name, str)
        assert name
    names = {row["name"] for row in channels}
    assert "telegram" in names
    assert "webchat" in names
