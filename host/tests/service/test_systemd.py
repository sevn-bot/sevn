"""``sevn service`` on a systemd ``--user`` manager (plan 0025 D1, W2).

Every test drives a ``FakeRunner`` installed through
``sevn.service.runner.use_runner``; no real ``systemctl``, ``journalctl`` or
``loginctl`` runs. ``HOME`` is a temp directory.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fakes.fake_runner import FakeRunner
from support.service import (
    combined,
    invoke,
    status_json,
    unit_environment,
    unit_exec_start,
    unit_words,
)

_GOLDEN = Path(__file__).with_name("golden") / "sevn.service"
_EXE = Path("/opt/sevn/bin/sevn")
_HOME = Path("/srv/sevn")
_UNIT = "sevn.service"


@dataclass
class LinuxHost:
    user_home: Path
    data_home: Path
    unit_path: Path
    runner: FakeRunner


@pytest.fixture
def linux_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinuxHost]:
    from sevn.service.runner import use_runner

    user_home = tmp_path / "user"
    user_home.mkdir()
    data_home = tmp_path / "data"
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("SEVN_HOME", str(data_home))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("LOGNAME", "tester")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    unit_path = user_home / ".config" / "systemd" / "user" / _UNIT
    runner = FakeRunner(watch=unit_path)
    runner.on("loginctl", "show-user", stdout="Linger=yes\n")
    use_runner(runner)
    try:
        yield LinuxHost(user_home, data_home, unit_path, runner)
    finally:
        use_runner(None)


# --- rendering ---------------------------------------------------------------


def test_unit_golden() -> None:
    from sevn.service.systemd import render_unit

    assert render_unit(_EXE, _HOME) == _GOLDEN.read_text(encoding="utf-8")


def test_unit_port_option_extends_exec_start() -> None:
    from sevn.service.systemd import render_unit

    text = render_unit(_EXE, _HOME, port=9001)
    assert unit_exec_start(text) == [str(_EXE), "serve", "--port", "9001"]


@pytest.mark.parametrize(
    ("exe", "home"),
    [
        (Path("/opt/my tools/sevn"), Path("/srv/my sevn")),
        (Path("/opt/sevn/bin/sevn"), Path("/srv/100%/sevn")),
        (Path("/opt/sevn/bin/sevn"), Path("/srv/über sevn")),
    ],
    ids=["spaces", "percent", "unicode"],
)
def test_unit_quotes_paths_systemd_would_split(exe: Path, home: Path) -> None:
    from sevn.service.systemd import render_unit

    text = render_unit(exe, home)
    assert unit_exec_start(text)[0] == str(exe)
    assert unit_environment(text) == {"SEVN_HOME": str(home)}


def test_unit_words_helper_matches_systemd_quoting() -> None:
    # Guards the helper the quoting test relies on.
    assert unit_words('"/a b/sevn" serve') == ["/a b/sevn", "serve"]
    assert unit_words('"SEVN_HOME=/x 100%%"') == ["SEVN_HOME=/x 100%"]


# --- install -----------------------------------------------------------------


def test_install_runs_bootstrap_or_enable_now(linux_host: LinuxHost) -> None:
    result = invoke(["service", "install"])
    assert result.exit_code == 0, combined(result)
    text = linux_host.unit_path.read_text(encoding="utf-8")
    exec_start = unit_exec_start(text)
    assert Path(exec_start[0]).is_absolute()
    assert Path(exec_start[0]).name == "sevn"
    assert exec_start[1:] == ["serve"]
    assert unit_environment(text) == {"SEVN_HOME": str(linux_host.data_home.resolve())}
    reload_at = linux_host.runner.index("systemctl", "--user", "daemon-reload")
    enable_at = linux_host.runner.index("systemctl", "--user", "enable", "--now", _UNIT)
    assert reload_at >= 0, linux_host.runner.argvs()
    assert enable_at > reload_at, linux_host.runner.argvs()
    assert linux_host.runner.calls[reload_at].watched == text.encode()
    assert all(argv[0] != "sudo" for argv in linux_host.runner.argvs())


def test_install_honours_home_and_port_options(
    linux_host: LinuxHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = invoke(["service", "install", "--home", "relative-home", "--port", "9100"])
    assert result.exit_code == 0, combined(result)
    text = linux_host.unit_path.read_text(encoding="utf-8")
    assert unit_environment(text) == {"SEVN_HOME": str((tmp_path / "relative-home").resolve())}
    assert unit_exec_start(text)[1:] == ["serve", "--port", "9100"]


def test_install_honours_xdg_config_home(
    linux_host: LinuxHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    result = invoke(["service", "install"])
    assert result.exit_code == 0, combined(result)
    assert (config_home / "systemd" / "user" / _UNIT).is_file()
    assert not linux_host.unit_path.exists()


def test_install_is_idempotent(linux_host: LinuxHost) -> None:
    first = invoke(["service", "install"])
    assert first.exit_code == 0, combined(first)
    before = linux_host.unit_path.read_bytes()
    stamp = linux_host.unit_path.stat().st_mtime_ns
    time.sleep(0.01)
    second = invoke(["service", "install"])
    assert second.exit_code == 0, combined(second)
    assert linux_host.unit_path.read_bytes() == before
    assert linux_host.unit_path.stat().st_mtime_ns == stamp
    assert "unchanged" in combined(second)


def test_other_unit_needs_force(linux_host: LinuxHost) -> None:
    linux_host.unit_path.parent.mkdir(parents=True)
    foreign = b"[Service]\nExecStart=/usr/bin/somebody-else\n"
    linux_host.unit_path.write_bytes(foreign)

    refused = invoke(["service", "install"])
    assert refused.exit_code == 1, combined(refused)
    assert "--force" in combined(refused)
    assert str(linux_host.unit_path) in combined(refused)
    assert linux_host.unit_path.read_bytes() == foreign
    assert linux_host.runner.find("systemctl", "--user", "enable") == []

    forced = invoke(["service", "install", "--force"])
    assert forced.exit_code == 0, combined(forced)
    text = linux_host.unit_path.read_text(encoding="utf-8")
    assert unit_exec_start(text)[1:] == ["serve"]
    enables = linux_host.runner.find("systemctl", "--user", "enable", "--now", _UNIT)
    assert enables, linux_host.runner.argvs()
    assert enables[-1].watched == text.encode()


def test_install_reports_systemctl_failure(linux_host: LinuxHost) -> None:
    linux_host.runner.on(
        "systemctl",
        "--user",
        "daemon-reload",
        returncode=1,
        stderr="Failed to connect to bus: No medium found\n",
    )
    result = invoke(["service", "install"])
    assert result.exit_code == 1, combined(result)
    assert "Failed to connect to bus: No medium found" in combined(result)
    assert linux_host.runner.find("systemctl", "--user", "enable") == []


# --- status ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("installed", "show", "state", "exit_code"),
    [
        (True, "LoadState=loaded\nActiveState=active\nSubState=running\nExecMainStatus=0\n",
         "running", None),
        (True, "LoadState=loaded\nActiveState=inactive\nSubState=dead\nExecMainStatus=0\n",
         "stopped", 0),
        (True, "LoadState=loaded\nActiveState=failed\nSubState=failed\nExecMainStatus=3\n",
         "failed", 3),
        (False, "LoadState=not-found\nActiveState=inactive\nSubState=dead\nExecMainStatus=0\n",
         "not-installed", None),
    ],
    ids=["running", "stopped", "failed", "not-installed"],
)  # fmt: skip
def test_status_maps_states(
    linux_host: LinuxHost, installed: bool, show: str, state: str, exit_code: int | None
) -> None:
    if installed:
        linux_host.unit_path.parent.mkdir(parents=True)
        linux_host.unit_path.write_text("[Service]\nExecStart=/x serve\n", encoding="utf-8")
    linux_host.runner.on("systemctl", "--user", "show", _UNIT, stdout=show)
    body = status_json(invoke(["service", "status", "--json"]))
    assert body == {"state": state, "exit_code": exit_code}


def test_status_text_names_the_state(linux_host: LinuxHost) -> None:
    linux_host.unit_path.parent.mkdir(parents=True)
    linux_host.unit_path.write_text("[Service]\nExecStart=/x serve\n", encoding="utf-8")
    linux_host.runner.on(
        "systemctl",
        "--user",
        "show",
        _UNIT,
        stdout="LoadState=loaded\nActiveState=failed\nExecMainStatus=7\n",
    )
    result = invoke(["service", "status"])
    assert result.exit_code == 0, combined(result)
    assert "failed" in result.stdout
    assert "7" in result.stdout


# --- linger ------------------------------------------------------------------


@pytest.mark.parametrize(("linger", "hint"), [("no", True), ("yes", False)])
def test_linger_off_prints_hint_and_never_runs_loginctl(
    linux_host: LinuxHost, linger: str, hint: bool
) -> None:
    linux_host.runner.on("loginctl", "show-user", stdout=f"Linger={linger}\n")
    result = invoke(["service", "install"])
    assert result.exit_code == 0, combined(result)
    assert ("loginctl enable-linger" in combined(result)) is hint
    assert linux_host.runner.find("loginctl", "show-user"), linux_host.runner.argvs()
    for argv in linux_host.runner.argvs():
        assert "enable-linger" not in argv, argv
        assert argv[0] != "sudo", argv


# --- uninstall, restart, logs ------------------------------------------------


def test_uninstall_stops_and_removes(linux_host: LinuxHost) -> None:
    installed = invoke(["service", "install"])
    assert installed.exit_code == 0, combined(installed)
    linux_host.runner.calls.clear()

    result = invoke(["service", "uninstall"])
    assert result.exit_code == 0, combined(result)
    assert not linux_host.unit_path.exists()
    disable_at = linux_host.runner.index("systemctl", "--user", "disable", "--now", _UNIT)
    assert disable_at >= 0, linux_host.runner.argvs()
    assert linux_host.runner.calls[disable_at].watched is not None
    reloads = linux_host.runner.find("systemctl", "--user", "daemon-reload")
    assert reloads, linux_host.runner.argvs()
    assert reloads[-1].watched is None


def test_uninstall_when_not_installed_is_a_noop(linux_host: LinuxHost) -> None:
    result = invoke(["service", "uninstall"])
    assert result.exit_code == 0, combined(result)
    assert "not-installed" in combined(result)
    assert linux_host.runner.find("systemctl", "--user", "disable") == []


def test_restart_restarts_the_unit(linux_host: LinuxHost) -> None:
    result = invoke(["service", "restart"])
    assert result.exit_code == 0, combined(result)
    assert linux_host.runner.find("systemctl", "--user", "restart", _UNIT)


def test_logs_wraps_journalctl(linux_host: LinuxHost) -> None:
    linux_host.runner.on("journalctl", stdout="line one\nline two\n")
    result = invoke(["service", "logs"])
    assert result.exit_code == 0, combined(result)
    assert linux_host.runner.find("journalctl", "--user", "-u", _UNIT)
    assert all("-f" not in argv for argv in linux_host.runner.argvs())
    assert "line two" in result.stdout


# --- default runner ----------------------------------------------------------


def test_default_runner_captures_output_and_exit_code() -> None:
    from sevn.service.runner import run

    result = run([sys.executable, "-c", "import sys; print('out'); sys.exit(4)"])
    assert result.returncode == 4
    assert result.stdout.strip() == "out"


def test_default_runner_reports_missing_binary_as_127(tmp_path: Path) -> None:
    from sevn.service.runner import run

    result = run([str(tmp_path / "no-such-binary")])
    assert result.returncode == 127
    assert result.stderr != ""


def test_default_runner_times_out_as_124() -> None:
    from sevn.service.runner import run

    started = time.monotonic()
    result = run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert result.returncode == 124
    assert time.monotonic() - started < 10


def test_unsupported_platform_is_refused(
    linux_host: LinuxHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    result = invoke(["service", "install"])
    assert result.exit_code == 2, combined(result)
    assert "sevn service supports macOS and Linux" in combined(result)
    assert linux_host.runner.calls == []
    assert not os.path.lexists(linux_host.unit_path)


# --- WV F2: an unchanged reinstall restarts a running service (D13) ----------

_SHOW = "LoadState=loaded\nActiveState={active}\nSubState={sub}\nExecMainStatus=0\n"


@pytest.mark.parametrize(
    ("active", "sub", "restarted"),
    [
        ("active", "running", True),
        ("inactive", "dead", False),
        ("failed", "failed", False),
    ],
    ids=["running", "stopped", "failed"],
)
def test_unchanged_install_restarts_only_a_running_service(
    linux_host: LinuxHost, active: str, sub: str, restarted: bool
) -> None:
    first = invoke(["service", "install"])
    assert first.exit_code == 0, combined(first)
    linux_host.runner.on(
        "systemctl", "--user", "show", _UNIT, stdout=_SHOW.format(active=active, sub=sub)
    )
    linux_host.runner.calls.clear()

    second = invoke(["service", "install"])
    assert second.exit_code == 0, combined(second)
    assert "unchanged" in combined(second)
    restarts = linux_host.runner.find("systemctl", "--user", "restart", _UNIT)
    restarts += linux_host.runner.find("systemctl", "--user", "try-restart", _UNIT)
    assert bool(restarts) is restarted, linux_host.runner.argvs()
    # A stopped service is never started by a plain restart.
    if not restarted:
        assert linux_host.runner.find("systemctl", "--user", "restart") == []
        assert linux_host.runner.find("systemctl", "--user", "start") == []
