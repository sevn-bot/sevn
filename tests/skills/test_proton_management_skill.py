"""Bundled ``proton-management`` skill tests."""

from __future__ import annotations

import json
import subprocess
import sys

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.proton_management import (
    PROTON_MANAGEMENT_SKILL_ID,
    cli_argv,
    dry_run_requested,
    status_payload,
)

_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / PROTON_MANAGEMENT_SKILL_ID
_SCRIPTS = _SKILL_ROOT / "scripts"


def test_dry_run_env(monkeypatch) -> None:
    monkeypatch.delenv("SEVN_PROTON_DRY_RUN", raising=False)
    assert dry_run_requested(cli_flag=False) is False
    monkeypatch.setenv("SEVN_PROTON_DRY_RUN", "1")
    assert dry_run_requested(cli_flag=False) is True


def test_status_payload() -> None:
    payload = status_payload(profile="default")
    assert "cli_installed" in payload
    assert payload["profile"] == "default"


def test_cli_argv_module_mode_profile_before_subcommand() -> None:
    argv = cli_argv(["pass", "vaults", "list"], profile="work", module_mode=True)
    assert argv == ["-m", "proton_cli", "--profile", "work", "pass", "vaults", "list"]


def test_cli_argv_binary_profile_before_subcommand() -> None:
    argv = cli_argv(["pass", "vaults", "list"], profile="work", module_mode=False)
    assert argv == ["--profile", "work", "pass", "vaults", "list"]


def test_status_script_json() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "status.py"), "--profile", "test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["data"]["skill"] == PROTON_MANAGEMENT_SKILL_ID


def test_pass_vaults_list_dry_run() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "pass_vaults_list.py"), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["data"]["mode"] == "dry_run"
    assert data["data"]["command"] == ["pass", "vaults", "list", "--output", "json"]
