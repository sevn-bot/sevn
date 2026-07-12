"""``sevn proxy logs`` (`specs/23-cli.md`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.log_follow import resolve_service_log_path, run_service_logs


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _install_home(base: Path) -> Path:
    home = base / ".sevn"
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
    (ws / "logs").mkdir(exist_ok=True)
    return home


def test_resolve_proxy_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _install_home(tmp_path)
    monkeypatch.setenv("SEVN_HOME", str(home))
    path = resolve_service_log_path(service="proxy", operator_home=home)
    assert path == home / "workspace" / "logs" / "proxy.log"


def test_proxy_logs_no_follow_prints_tail(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(tmp_path)
    log_path = home / "workspace" / "logs" / "proxy.log"
    log_path.write_text("line-one\nline-two\n", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    with patch("sevn.cli.log_follow._probe_proxy_running", return_value=False):
        result = runner.invoke(get_command(app), ["proxy", "logs", "--no-follow", "-n", "1"])
    assert result.exit_code == 0
    assert "line-two" in result.stdout


def test_run_proxy_logs_exits_when_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import click

    home = _install_home(tmp_path)
    monkeypatch.setenv("SEVN_HOME", str(home))
    with (
        patch("sevn.cli.log_follow.unit_is_active", return_value=False),
        patch("sevn.cli.log_follow._probe_proxy_running", return_value=False),
        pytest.raises(click.exceptions.Exit) as exc,
    ):
        run_service_logs(service="proxy", lines=10, follow=True, operator_home=home)
    assert exc.value.exit_code == 4
