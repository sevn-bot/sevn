"""Fresh-machine onboarding gate (`specs/22-onboarding.md` §9, Wave 9 Agent 9A)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.onboarding.validate import validate_workspace_document

_FIXTURE_CONFIG = Path(__file__).resolve().parents[1] / "fixtures" / "config" / "schema_v1_min.json"


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_onboard_config_fresh_machine_writes_valid_sevn_json(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sevn onboard --config`` on empty ``SEVN_HOME`` produces schema-valid ``sevn.json``."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    sevn_json = home / "workspace" / "sevn.json"
    assert not sevn_json.is_file()

    with (
        patch("sevn.cli.install_gate.install_daemon_plan") as mock_install,
        patch(
            "sevn.onboarding.service_restart.restart_services_after_promote",
            return_value={"ok": True, "message": "gateway started"},
        ),
    ):
        mock_install.return_value = "service units (launchd): g + p"
        result = runner.invoke(
            get_command(app),
            [
                "onboard",
                "--config",
                str(_FIXTURE_CONFIG),
                "--no-prompt-bot-name",
                "--bot-name",
                "TestBot",
            ],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert sevn_json.is_file()

    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    validate_workspace_document(doc)
    assert doc["schema_version"] == 1
    assert doc["gateway"]["port"] == 3001
