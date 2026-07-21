"""PR #38/#41/#43 skill-bridge RED tests (green after W4 / W7 / W9).

Appends behavioral coverage beyond dry-run/status in ``test_proton_management_skill.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import AsyncMock, patch

import pytest

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.proton_management import (
    PROTON_MANAGEMENT_SKILL_ID,
    cli_argv,
    run_proton_cli,
    run_proton_cli_async,
)

_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / PROTON_MANAGEMENT_SKILL_ID
_SCRIPTS = _SKILL_ROOT / "scripts"


def test_cli_argv_module_mode_profile_before_subcommand_contract() -> None:
    """``python -m proton_cli --profile work pass …`` — profile before subcommand."""
    argv = cli_argv(["pass", "vaults", "list"], profile="work", module_mode=True)
    assert argv[:4] == ["-m", "proton_cli", "--profile", "work"]
    assert argv[4:] == ["pass", "vaults", "list"]


def test_run_proton_cli_uses_module_mode_profile_order() -> None:
    def fake_which(name: str) -> str | None:
        if name == "proton-cli":
            return None
        if name in ("python3", "python"):
            return sys.executable
        return None

    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"[]", b""))
    with (
        patch("sevn.skills.proton_management.shutil.which", side_effect=fake_which),
        patch("asyncio.create_subprocess_exec", return_value=proc) as mocked,
    ):
        code, _out, _err = run_proton_cli(
            ["pass", "vaults", "list"],
            profile="work",
        )
    assert code == 0
    cmd = list(mocked.call_args.args)
    # Expect ``python -m proton_cli --profile work pass vaults list …``
    assert "-m" in cmd
    assert "proton_cli" in cmd
    profile_idx = cmd.index("--profile")
    pass_idx = cmd.index("pass")
    assert profile_idx < pass_idx


@pytest.mark.xfail(reason="green after W7: mail_list dry-run", strict=False)
def test_mail_list_dry_run() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "mail_list.py"), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["data"]["mode"] == "dry_run"
    assert "mail" in " ".join(map(str, data["data"]["command"]))


@pytest.mark.xfail(reason="green after W7: mail_read dry-run", strict=False)
def test_mail_read_dry_run() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "mail_read.py"), "msg-1", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["data"]["mode"] == "dry_run"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W7: run_proton_cli_async argv", strict=False)
async def test_run_proton_cli_async_assembles_argv() -> None:
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"ok", b""))
    with (
        patch("sevn.skills.proton_management.shutil.which", return_value=None),
        patch("asyncio.create_subprocess_exec", return_value=proc) as mocked,
    ):
        code, out, _err = await run_proton_cli_async(
            ["pass", "vaults", "list"],
            profile="work",
        )
    assert code == 0
    assert out == "ok"
    argv = list(mocked.call_args.args)
    assert "--profile" in argv
    assert argv.index("--profile") < argv.index("pass")


@pytest.mark.xfail(reason="green after W9: calendar_events_list dry-run", strict=False)
def test_calendar_events_list_dry_run() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "calendar_events_list.py"), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["data"]["mode"] == "dry_run"


@pytest.mark.xfail(reason="green after W9: contacts_list dry-run", strict=False)
def test_contacts_list_dry_run() -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "contacts_list.py"), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["data"]["mode"] == "dry_run"
