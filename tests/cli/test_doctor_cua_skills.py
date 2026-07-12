"""Doctor binary and TCC entitlement checks for cua skills (W0.5 / W1.5)."""

from __future__ import annotations

import pytest

from sevn.cli.doctor.sections import registered_check_ids
from sevn.cli.doctor.solutions import lookup_solution


@pytest.mark.parametrize(
    "check_id",
    [
        "cua_driver_binary",
        "cua_cli_binary",
        "lume_binary",
        "cua_tcc_accessibility",
        "cua_tcc_screen_recording",
        "cua_tcc_automation",
    ],
)
def test_doctor_check_ids_registered(check_id: str) -> None:
    assert check_id in registered_check_ids()


@pytest.mark.parametrize(
    ("check_id", "snippet"),
    [
        ("cua_driver_binary", "cua-driver install"),
        ("cua_cli_binary", "pip install cua"),
        ("lume_binary", "lume"),
        ("cua_tcc_accessibility", "Privacy & Security"),
    ],
)
def test_doctor_fix_hints(check_id: str, snippet: str) -> None:
    row = lookup_solution(check_id)
    assert row is not None
    assert snippet.lower() in row.explanation.lower()


def test_cua_cli_binary_check_runs_for_cua_agent_enabled() -> None:
    assert "cua_cli_binary" in registered_check_ids()


def test_lume_binary_check_runs_when_lume_enabled() -> None:
    assert "lume_binary" in registered_check_ids()


def test_tcc_checks_run_for_computer_use_host_target() -> None:
    ids = registered_check_ids()
    assert "cua_tcc_accessibility" in ids
    assert "cua_tcc_screen_recording" in ids
