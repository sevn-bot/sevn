"""Unit tests for compose helpers (mocked subprocess / HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sevn_telegram_tester.compose import (
    COMPOSE_OVERRIDE,
    apply_local_e2e_compose,
    repo_root,
    wait_for_gateway_ready,
)
from sevn_telegram_tester.config import TelegramTesterSettings


def test_repo_root_points_at_docker_compose() -> None:
    root = repo_root()
    assert (root / "docker/docker-compose.yml").is_file()


def test_compose_override_file_exists() -> None:
    assert COMPOSE_OVERRIDE.is_file()
    text = COMPOSE_OVERRIDE.read_text(encoding="utf-8")
    assert "SEVN_E2E_ECHO_DELAY_MS" in text
    assert "SEVN_E2E_ECHO_TURN" in text


def test_apply_local_e2e_compose_invokes_docker() -> None:
    settings = TelegramTesterSettings()
    proc = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("sevn_telegram_tester.compose.subprocess.run", return_value=proc) as run_mock,
        patch("sevn_telegram_tester.compose.wait_for_gateway_ready") as ready_mock,
    ):
        apply_local_e2e_compose(settings)
    ready_mock.assert_called_once_with(settings)
    cmd = run_mock.call_args[0][0]
    assert "compose" in cmd
    assert str(COMPOSE_OVERRIDE) in cmd


def test_wait_for_gateway_ready_success() -> None:
    settings = TelegramTesterSettings(sevn_gateway_port=3001)
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    with patch("sevn_telegram_tester.compose.urllib.request.urlopen", return_value=resp):
        wait_for_gateway_ready(settings, timeout_s=1.0, interval_s=0.01)


def test_wait_for_gateway_ready_times_out() -> None:
    settings = TelegramTesterSettings(sevn_gateway_port=39999)
    with (
        patch(
            "sevn_telegram_tester.compose.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ),
        pytest.raises(TimeoutError),
    ):
        wait_for_gateway_ready(settings, timeout_s=0.05, interval_s=0.01)
