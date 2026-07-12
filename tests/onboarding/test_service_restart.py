"""Paired service restart after onboarding promote."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sevn.onboarding.service_restart import restart_services_after_promote


def test_restart_uses_daemon_path_when_units_exist(tmp_path: Path) -> None:
    sj = tmp_path / "sevn.json"
    _ = sj.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    calls: list[tuple[str, str]] = []

    def _fake_control(*, home: Path, service: str, action: str, dry_run: bool = False) -> str:
        calls.append((service, action))
        return f"{service} {action}: ok"

    with (
        patch("sevn.onboarding.service_restart.unit_file_exists", return_value=True),
        patch("sevn.onboarding.service_restart.stop_paired_units") as stop_mock,
        patch("sevn.onboarding.service_restart.propagate_daemon_secret_env") as secret_env_mock,
        patch("sevn.onboarding.service_restart.propagate_daemon_proxy_env") as proxy_env_mock,
        patch("sevn.onboarding.service_restart.control_unit", side_effect=_fake_control),
        patch("sevn.onboarding.service_restart.stop_handoff_listeners") as handoff_mock,
        patch("sevn.onboarding.service_restart._wait_for_ports_absent"),
    ):
        body = restart_services_after_promote(sevn_json_path=sj)

    stop_mock.assert_called_once()
    handoff_mock.assert_called_once()
    secret_env_mock.assert_called_once()
    proxy_env_mock.assert_called_once()
    assert calls == [("proxy", "start"), ("gateway", "start")]
    assert body["mode"] == "daemon"
