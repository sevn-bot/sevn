"""Paired gateway + proxy daemon control (`specs/23-cli.md` §4.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.cli.daemon_control import _mutate_gateway_with_proxy
from sevn.cli.service_manager import ServiceManagerError


def test_gateway_start_proxy_first_when_proxy_unit_exists(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_control(*, home: Path, service: str, action: str, dry_run: bool = False) -> str:
        calls.append((service, action))
        return f"{service} {action}: ok"

    with (
        patch("sevn.cli.daemon_control.unit_file_exists", return_value=True),
        patch("sevn.cli.daemon_control.control_unit", side_effect=_fake_control),
    ):
        lines = _mutate_gateway_with_proxy(home=tmp_path, action="start")

    assert calls == [("proxy", "start"), ("gateway", "start")]
    assert lines == ["proxy start: ok", "gateway start: ok"]


def test_gateway_start_gateway_only_when_proxy_unit_missing(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_control(*, home: Path, service: str, action: str, dry_run: bool = False) -> str:
        calls.append((service, action))
        return f"{service} {action}: ok"

    with (
        patch("sevn.cli.daemon_control.unit_file_exists", return_value=False),
        patch("sevn.cli.daemon_control.control_unit", side_effect=_fake_control),
    ):
        lines = _mutate_gateway_with_proxy(home=tmp_path, action="start")

    assert calls == [("gateway", "start")]
    assert lines == ["gateway start: ok"]


def test_gateway_start_fails_when_proxy_start_fails(tmp_path: Path) -> None:
    def _fake_control(*, home: Path, service: str, action: str, dry_run: bool = False) -> str:
        if service == "proxy":
            msg = "launchctl bootstrap failed"
            raise ServiceManagerError(msg)
        return f"{service} {action}: ok"

    with (
        patch("sevn.cli.daemon_control.unit_file_exists", return_value=True),
        patch("sevn.cli.daemon_control.control_unit", side_effect=_fake_control),
        pytest.raises(ServiceManagerError, match="launchctl bootstrap failed"),
    ):
        _mutate_gateway_with_proxy(home=tmp_path, action="start")


def test_gateway_stop_runs_gateway_and_proxy_in_parallel(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_control(*, home: Path, service: str, action: str, dry_run: bool = False) -> str:
        calls.append((service, action))
        return f"{service} {action}: ok"

    with (
        patch("sevn.cli.daemon_control.unit_file_exists", return_value=True),
        patch("sevn.cli.daemon_control.control_unit", side_effect=_fake_control),
    ):
        lines = _mutate_gateway_with_proxy(home=tmp_path, action="stop")

    assert sorted(calls) == [("gateway", "stop"), ("proxy", "stop")]
    assert sorted(lines) == ["gateway stop: ok", "proxy stop: ok"]


def test_gateway_restart_proxy_first_when_proxy_unit_exists(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_control(*, home: Path, service: str, action: str, dry_run: bool = False) -> str:
        calls.append((service, action))
        return f"{service} {action}: ok"

    with (
        patch("sevn.cli.daemon_control.unit_file_exists", return_value=True),
        patch("sevn.cli.daemon_control.control_unit", side_effect=_fake_control),
    ):
        lines = _mutate_gateway_with_proxy(home=tmp_path, action="restart")

    assert calls == [("proxy", "restart"), ("gateway", "restart")]
    assert lines == ["proxy restart: ok", "gateway restart: ok"]
