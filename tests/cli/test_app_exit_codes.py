"""Typer exit codes (`specs/23-cli.md` §2.10).

Regression anchors: exit-code policy lives with named tests in this module
(e.g. ``test_gateway_status_json_envelope`` for JSON failure exit **4**).
"""

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


def test_onboard_noninteractive_bad_parameter(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["onboard"])
    assert result.exit_code == 2


def test_gateway_status_json_envelope(runner: ClickCliRunner) -> None:
    from unittest.mock import patch

    with patch(
        "sevn.cli.daemon_control.control_unit",
        return_value="gateway (launchd): inactive",
    ):
        result = runner.invoke(get_command(app), ["gateway", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["command"] == "sevn gateway status"
    assert isinstance(payload["data"]["status"], str)


def test_version_json(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["version", "--json"])
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert "cli_version" in body
    assert "python_version" in body
    assert "gateway_api_min" in body


def test_secrets_list_without_bound_workspace_exit4(
    runner: ClickCliRunner,
    tmp_path: Path,
) -> None:
    """``secrets list`` requires operator-bound ``sevn.json`` (`specs/23-cli.md` §2.2)."""
    empty_home = tmp_path / "empty"
    empty_home.mkdir()
    result = runner.invoke(
        get_command(app),
        ["secrets", "list"],
        env={"SEVN_HOME": str(empty_home)},
    )
    assert result.exit_code == 4
