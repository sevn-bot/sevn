"""Gateway teardown helpers for ``sevn unboard``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sevn.cli.gateway_teardown import (
    _is_sevn_gateway_cmdline,
    _kill_orphan_gateway,
    stop_all_gateway_instances,
)
from sevn.config.workspace_config import WorkspaceConfig


def test_is_sevn_gateway_cmdline() -> None:
    assert _is_sevn_gateway_cmdline("uv run uvicorn sevn.gateway.http_server:create_app --factory")
    assert not _is_sevn_gateway_cmdline("python -m http.server 3001")


def test_kill_orphan_gateway_terminates_without_health_probe() -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    with (
        patch("sevn.cli.gateway_teardown._pids_on_port", return_value=[4242]),
        patch(
            "sevn.cli.gateway_teardown._read_cmdline",
            return_value="uvicorn sevn.gateway.http_server:create_app --factory",
        ),
        patch("sevn.cli.gateway_teardown._terminate_pid") as term_mock,
    ):
        _kill_orphan_gateway(workspace_cfg=cfg, dry_run=False)
    term_mock.assert_called_once_with(4242, dry_run=False)


def test_stop_all_gateway_instances_dry_run(tmp_path: Path) -> None:
    home = tmp_path / ".sevn"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    with (
        patch("sevn.cli.gateway_teardown.stop_paired_units") as stop_mock,
        patch("sevn.cli.gateway_teardown.remove_paired_unit_files"),
        patch("sevn.cli.gateway_teardown._kill_orphan_gateway"),
    ):
        stop_all_gateway_instances(operator_home=home, dry_run=True)
    stop_mock.assert_called_once()
