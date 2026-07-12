"""Argv parsing for ``sevn onboard --config``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.onboarding.fast_onboard import FastOnboardResult

# NO_COLOR only strips color; Rich still emits bold/dim styling that splits
# option strings like ``--config`` across escape sequences. Strip all SGR
# codes before substring assertions so they hold under any renderer.
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_SGR_RE.sub("", text)


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_onboard_profile_json_path_suggests_config(
    runner: ClickCliRunner,
) -> None:
    """``--profile sevn_test.json`` hints to use ``--config`` instead."""
    result = runner.invoke(
        get_command(app),
        ["onboard", "--profile", "sevn_test.json"],
        env={"NO_COLOR": "1"},
    )
    assert result.exit_code != 0
    combined = _strip_ansi(result.stderr + result.stdout)
    assert "--config" in combined
    assert "sevn_test.json" in combined


def test_onboard_positional_config_file(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positional config path is accepted as shorthand for ``--config``."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    cfg = tmp_path / "sevn_test.json"
    cfg.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "agent": {"display_name": "Luluu"},
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
    fake = FastOnboardResult(
        sevn_json_path=home / "workspace" / "sevn.json",
        seeded_paths=(),
        daemon_install_line=None,
        pdf_native_install_line=None,
        services_restart=None,
    )
    with patch(
        "sevn.cli.commands.onboard.run_fast_onboard",
        new=AsyncMock(return_value=fake),
    ):
        result = runner.invoke(
            get_command(app),
            ["onboard", str(cfg), "--no-prompt-bot-name"],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
