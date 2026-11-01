"""Numeric filenames are output files, not file-descriptor duplication."""

from __future__ import annotations

from pathlib import Path

import pytest
from sevn.domain.bots import BotService
from sevn.runtime.approvals import auto_low
from sevn.runtime.events import ApprovalCall
from sevn.sandbox.risk import risk_of
from support.botcore import arm_configured, upgrade_home


@pytest.mark.parametrize("redirect", [">1", ">2", ">-", ">>1", ">|2", '>"&1"'])
async def test_numeric_output_files_require_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redirect: str
) -> None:
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof", access="full", approval_policy="auto")
    command = f"printf fixture {redirect}"
    assert risk_of(command) != "low"
    assert not auto_low(bot, ApprovalCall("call_fixture", "shell", {"command": command}))


@pytest.mark.parametrize(
    "command",
    [
        "printf fixture >&1",
        "printf fixture >&2",
        "printf fixture 2>&1",
        "printf fixture >/dev/null",
    ],
)
def test_fd_duplication_and_null_output_remain_low(command: str) -> None:
    assert risk_of(command) == "low"


@pytest.mark.parametrize("option", ["--compress-prog", "--compress-program", "--out", "--output"])
def test_sort_dangerous_long_option_prefix_is_not_low(option: str) -> None:
    assert risk_of(f"sort {option}=fixture -S 1K input") != "low"


def test_native_sort_accepts_compressor_abbreviation(tmp_path: Path) -> None:
    import shutil
    import subprocess

    binary = shutil.which("sort")
    compressor = shutil.which("gzip")
    assert binary is not None and compressor is not None
    fixture = tmp_path / "input"
    fixture.write_text("\n".join(str(number) for number in range(100, 0, -1)) + "\n")
    command = [binary, f"--compress-prog={compressor}", "-S", "1K", str(fixture)]
    ran = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)  # noqa: S603
    assert ran.returncode == 0, ran.stderr
    assert len(ran.stdout.splitlines()) == 100
    assert risk_of(" ".join(command)) != "low"
