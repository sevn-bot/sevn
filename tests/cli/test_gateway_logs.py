"""``sevn gateway logs`` (`specs/23-cli.md`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.log_follow import resolve_gateway_log_path, run_gateway_logs


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


def test_resolve_gateway_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _install_home(tmp_path)
    monkeypatch.setenv("SEVN_HOME", str(home))
    path = resolve_gateway_log_path(operator_home=home)
    assert path == home / "workspace" / "logs" / "gateway.log"


def test_gateway_logs_no_follow_prints_tail(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(tmp_path)
    log_path = home / "workspace" / "logs" / "gateway.log"
    log_path.write_text("line-one\nline-two\n", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    with patch("sevn.cli.log_follow.probe_gateway_listen_state", return_value="absent"):
        result = runner.invoke(get_command(app), ["gateway", "logs", "--no-follow", "-n", "1"])
    assert result.exit_code == 0
    assert "line-two" in result.stdout


def test_follow_file_throttles_health_probes(tmp_path: Path) -> None:
    from sevn.config.workspace_config import WorkspaceConfig

    log_path = tmp_path / "gateway.log"
    log_path.write_text("line\n", encoding="utf-8")
    with (
        patch("sevn.cli.log_follow.unit_is_active", return_value=False),
        patch("sevn.cli.log_follow.probe_gateway_listen_state", return_value="running") as probe,
        patch("sevn.cli.log_follow._STOP_CHECK_INTERVAL_S", 0.05),
        patch("sevn.cli.log_follow.time.sleep", side_effect=KeyboardInterrupt),
    ):
        from sevn.cli.log_follow import _follow_file

        _follow_file(
            log_path,
            service="gateway",
            workspace_cfg=WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            ),
            poll_s=0.01,
        )
    assert probe.call_count <= 3


def test_gateway_stopped_skips_health_when_unit_active() -> None:
    from sevn.cli.log_follow import _gateway_stopped

    with (
        patch("sevn.cli.log_follow.unit_is_active", return_value=True),
        patch("sevn.cli.log_follow.probe_gateway_listen_state") as probe,
    ):
        assert _gateway_stopped(workspace_cfg=object()) is False
    probe.assert_not_called()


def test_run_gateway_logs_exits_when_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import click

    home = _install_home(tmp_path)
    monkeypatch.setenv("SEVN_HOME", str(home))
    with (
        patch("sevn.cli.log_follow.unit_is_active", return_value=False),
        patch("sevn.cli.log_follow.probe_gateway_listen_state", return_value="absent"),
        pytest.raises(click.exceptions.Exit) as exc,
    ):
        run_gateway_logs(lines=10, follow=True, operator_home=home)
    assert exc.value.exit_code == 4
