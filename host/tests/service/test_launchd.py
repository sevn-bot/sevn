"""``sevn service`` as a launchd agent on macOS (plan 0025 D1, W2).

Every test drives a ``FakeRunner`` installed through
``sevn.service.runner.use_runner``; no real ``launchctl`` runs. ``HOME`` is a
temp directory, so nothing lands in the real ``~/Library/LaunchAgents``.
"""

from __future__ import annotations

import os
import plistlib
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_runner import FakeRunner
from support.service import combined, invoke, status_json

_GOLDEN = Path(__file__).with_name("golden") / "bot.sevn.host.plist"
_EXE = Path("/opt/sevn/bin/sevn")
_HOME = Path("/srv/sevn")
_LABEL = "bot.sevn.host"


@dataclass
class MacHost:
    user_home: Path
    data_home: Path
    plist_path: Path
    runner: FakeRunner
    domain: str


@pytest.fixture
def mac_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MacHost]:
    from sevn.service.runner import use_runner

    user_home = tmp_path / "user"
    user_home.mkdir()
    data_home = tmp_path / "data"
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("SEVN_HOME", str(data_home))
    monkeypatch.setattr(sys, "platform", "darwin")
    plist_path = user_home / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
    runner = FakeRunner(watch=plist_path)
    use_runner(runner)
    try:
        yield MacHost(user_home, data_home, plist_path, runner, f"gui/{os.getuid()}")
    finally:
        use_runner(None)


def _load(data: bytes | str) -> dict[str, Any]:
    raw = data.encode() if isinstance(data, str) else data
    loaded = plistlib.loads(raw)
    assert isinstance(loaded, dict)
    return loaded


# --- rendering ---------------------------------------------------------------


def test_plist_golden() -> None:
    from sevn.service.launchd import render_plist

    assert _load(render_plist(_EXE, _HOME)) == _load(_GOLDEN.read_bytes())


def test_plist_port_option_extends_program_arguments() -> None:
    from sevn.service.launchd import render_plist

    loaded = _load(render_plist(_EXE, _HOME, port=9001))
    assert loaded["ProgramArguments"] == [str(_EXE), "serve", "--port", "9001"]


def test_plist_keeps_paths_with_spaces_and_unicode_intact() -> None:
    from sevn.service.launchd import render_plist

    exe = Path("/Applications/My Tools/sevn")
    home = Path("/Users/zoë/Library/Application Support/sevn")
    loaded = _load(render_plist(exe, home))
    assert loaded["ProgramArguments"] == [str(exe), "serve"]
    assert loaded["EnvironmentVariables"] == {"SEVN_HOME": str(home)}
    assert loaded["StandardOutPath"] == str(home / "logs" / "service.log")


# --- install -----------------------------------------------------------------


def test_install_runs_bootstrap_or_enable_now(mac_host: MacHost) -> None:
    result = invoke(["service", "install"])
    assert result.exit_code == 0, combined(result)
    data = mac_host.plist_path.read_bytes()
    loaded = _load(data)
    program = loaded["ProgramArguments"]
    assert Path(program[0]).is_absolute()
    assert Path(program[0]).name == "sevn"
    assert program[1:] == ["serve"]
    home = mac_host.data_home.resolve()
    assert loaded["EnvironmentVariables"] == {"SEVN_HOME": str(home)}
    assert loaded["StandardOutPath"] == str(home / "logs" / "service.log")
    assert (home / "logs").is_dir()
    boots = mac_host.runner.find(
        "launchctl", "bootstrap", mac_host.domain, str(mac_host.plist_path)
    )
    assert boots, mac_host.runner.argvs()
    assert boots[-1].watched == data
    assert all(argv[0] != "sudo" for argv in mac_host.runner.argvs())


def test_install_is_idempotent(mac_host: MacHost) -> None:
    first = invoke(["service", "install"])
    assert first.exit_code == 0, combined(first)
    before = mac_host.plist_path.read_bytes()
    stamp = mac_host.plist_path.stat().st_mtime_ns
    time.sleep(0.01)
    second = invoke(["service", "install"])
    assert second.exit_code == 0, combined(second)
    assert mac_host.plist_path.read_bytes() == before
    assert mac_host.plist_path.stat().st_mtime_ns == stamp
    assert "unchanged" in combined(second)


def test_other_unit_needs_force(mac_host: MacHost) -> None:
    mac_host.plist_path.parent.mkdir(parents=True)
    foreign = plistlib.dumps({"Label": _LABEL, "ProgramArguments": ["/usr/bin/other"]})
    mac_host.plist_path.write_bytes(foreign)

    refused = invoke(["service", "install"])
    assert refused.exit_code == 1, combined(refused)
    assert "--force" in combined(refused)
    assert mac_host.plist_path.read_bytes() == foreign
    assert mac_host.runner.find("launchctl", "bootstrap") == []

    forced = invoke(["service", "install", "--force"])
    assert forced.exit_code == 0, combined(forced)
    data = mac_host.plist_path.read_bytes()
    assert _load(data)["ProgramArguments"][1:] == ["serve"]
    boots = mac_host.runner.find("launchctl", "bootstrap")
    assert boots, mac_host.runner.argvs()
    assert boots[-1].watched == data


def test_install_reports_launchctl_failure(mac_host: MacHost) -> None:
    mac_host.runner.on(
        "launchctl",
        "bootstrap",
        returncode=5,
        stderr="Bootstrap failed: 5: Input/output error\n",
    )
    result = invoke(["service", "install"])
    assert result.exit_code == 1, combined(result)
    assert "Bootstrap failed: 5: Input/output error" in combined(result)


def test_install_never_prints_linger_hint_on_macos(mac_host: MacHost) -> None:
    result = invoke(["service", "install"])
    assert result.exit_code == 0, combined(result)
    assert "enable-linger" not in combined(result)
    assert mac_host.runner.find("loginctl") == []


# --- status ------------------------------------------------------------------

_PRINT = (
    "{domain}/bot.sevn.host = {{\n"
    "\tactive count = 1\n\tstate = {state}\n\tlast exit code = {code}\n}}\n"
)


@pytest.mark.parametrize(
    ("installed", "printed", "returncode", "state", "exit_code"),
    [
        (True, ("running", "(never exited)"), 0, "running", None),
        (True, ("not running", "0"), 0, "stopped", 0),
        (True, ("not running", "3"), 0, "failed", 3),
        (True, None, 113, "stopped", None),
        (False, None, 113, "not-installed", None),
    ],
    ids=["running", "stopped", "failed", "not-loaded", "not-installed"],
)
def test_status_maps_states(
    mac_host: MacHost,
    installed: bool,
    printed: tuple[str, str] | None,
    returncode: int,
    state: str,
    exit_code: int | None,
) -> None:
    if installed:
        mac_host.plist_path.parent.mkdir(parents=True)
        mac_host.plist_path.write_bytes(plistlib.dumps({"Label": _LABEL}))
    stdout = ""
    stderr = ""
    if printed is not None:
        stdout = _PRINT.format(domain=mac_host.domain, state=printed[0], code=printed[1])
    else:
        stderr = f'Bad request.\nCould not find service "{_LABEL}" in domain for user gui\n'
    mac_host.runner.on(
        "launchctl",
        "print",
        f"{mac_host.domain}/{_LABEL}",
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
    body = status_json(invoke(["service", "status", "--json"]))
    assert body == {"state": state, "exit_code": exit_code}


# --- uninstall, restart, logs ------------------------------------------------


def test_uninstall_stops_and_removes(mac_host: MacHost) -> None:
    installed = invoke(["service", "install"])
    assert installed.exit_code == 0, combined(installed)
    mac_host.runner.calls.clear()

    result = invoke(["service", "uninstall"])
    assert result.exit_code == 0, combined(result)
    assert not mac_host.plist_path.exists()
    bootouts = mac_host.runner.find("launchctl", "bootout")
    assert bootouts, mac_host.runner.argvs()
    assert any(arg.startswith(mac_host.domain) for arg in bootouts[0].argv[2:])
    assert bootouts[0].watched is not None


def test_uninstall_when_not_installed_is_a_noop(mac_host: MacHost) -> None:
    result = invoke(["service", "uninstall"])
    assert result.exit_code == 0, combined(result)
    assert "not-installed" in combined(result)
    assert mac_host.runner.find("launchctl", "bootout") == []


def test_restart_kickstarts_the_agent(mac_host: MacHost) -> None:
    result = invoke(["service", "restart"])
    assert result.exit_code == 0, combined(result)
    assert mac_host.runner.find("launchctl", "kickstart", "-k", f"{mac_host.domain}/{_LABEL}")


def test_logs_tails_the_service_log(mac_host: MacHost) -> None:
    logs = mac_host.data_home / "logs"
    logs.mkdir(parents=True)
    (logs / "service.log").write_text("boot\nready on 127.0.0.1:8787\n", encoding="utf-8")
    result = invoke(["service", "logs"])
    assert result.exit_code == 0, combined(result)
    assert "ready on 127.0.0.1:8787" in result.stdout


def test_logs_without_a_log_names_the_path(mac_host: MacHost) -> None:
    result = invoke(["service", "logs"])
    assert result.exit_code == 1, combined(result)
    assert str(mac_host.data_home.resolve() / "logs" / "service.log") in combined(result)
