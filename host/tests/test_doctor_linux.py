"""``sevn doctor`` Linux checks and the ``sevn.system`` probes (plan 0025 D7, W3).

Doctor tests patch the probe functions on ``sevn.system`` (and
``sevn.secrets.probe_secret_service`` / ``sevn.runtime.installs.resolve``) and
run the CLI with ``PATH`` reduced to an empty temp directory, so no real
``claude``, ``bwrap``, ``systemctl`` or ``loginctl`` runs. Probe tests use temp
files, fake binaries and the ``FakeRunner``.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_keyring import FakeKeyring
from fakes.fake_runner import FakeRunner

_EXISTING_KEYS = {
    "home": str,
    "db": str,
    "secrets_backend": str,
    "web_dist": str,
    "version": str,
    "claude_present": bool,
    "claude_login": (int, type(None)),
    "jev_key": str,
    "ollama": str,
    "allow_cli_fallback": bool,
    "decisions_provider": str,
}
_LINUX_KEYS = ("platform", "service", "bubblewrap", "display", "portals", "linger")
_PROBES = {
    "probe_platform": "ubuntu 24.04",
    "probe_service": "running",
    "probe_bubblewrap": "ok",
    "probe_display": "wayland",
    "probe_portals": "xdg-desktop-portal (gnome)",
    "probe_linger": "off",
}
_KEY_FOR_PROBE = {
    "probe_platform": "platform",
    "probe_service": "service",
    "probe_bubblewrap": "bubblewrap",
    "probe_display": "display",
    "probe_portals": "portals",
    "probe_linger": "linger",
}
_USERNS_SYSCTL = "kernel.apparmor_restrict_unprivileged_userns"


# --- arrange -----------------------------------------------------------------


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str = "age-file") -> Path:
    home = tmp_path / "data"
    home.mkdir()
    user = tmp_path / "user"
    user.mkdir()
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_WORKSPACES", str(home / "workspaces"))
    monkeypatch.delenv("SEVN_SECRETS__BACKEND", raising=False)
    monkeypatch.delenv("SEVN_OLLAMA_URL", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    (home / "config.toml").write_text(f'[secrets]\nbackend = "{backend}"\n', encoding="utf-8")
    return home


def _patch_probes(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, Callable[..., object]]
) -> None:
    for name, fake in values.items():
        monkeypatch.setattr(f"sevn.system.{name}", fake)


def _constant(value: object) -> Callable[..., object]:
    def probe(*_args: object, **_kwargs: object) -> object:
        return value

    return probe


def _fake_resolve(name: str) -> object:
    from sevn.runtime.installs import Resolved

    if name == "claude":
        return Resolved(Path("/opt/sevn/runtimes/claude/2.1.309/claude"), "managed", "2.1.309")
    if name == "opencode":
        return Resolved(Path("/usr/bin/opencode"), "system", None)
    return None


def _doctor(*args: str) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, ["doctor", *args])


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, f"{result.output}\n{getattr(result, 'stderr', '')}"
    body = json.loads(result.stdout)
    assert isinstance(body, dict)
    return body


@pytest.fixture
def linux_doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_probes(monkeypatch, {name: _constant(value) for name, value in _PROBES.items()})
    monkeypatch.setattr("sevn.runtime.installs.resolve", _fake_resolve)
    return home


# --- doctor keys -------------------------------------------------------------


@pytest.mark.parametrize("probe", sorted(_PROBES))
def test_doctor_reports_each_linux_key(linux_doctor: Path, probe: str) -> None:
    body = _json(_doctor("--json"))
    assert body[_KEY_FOR_PROBE[probe]] == _PROBES[probe]


def test_doctor_reports_runtimes_with_version_and_source(linux_doctor: Path) -> None:
    body = _json(_doctor("--json"))
    runtimes = body["runtimes"]
    assert set(runtimes) == {"claude", "opencode", "codex", "cursor-agent"}
    assert runtimes["claude"] == {"source": "managed", "version": "2.1.309"}
    assert runtimes["opencode"] == {"source": "system", "version": None}
    assert runtimes["codex"] == {"source": "none", "version": None}
    assert runtimes["cursor-agent"] == {"source": "none", "version": None}


def test_doctor_text_output_lists_linux_keys(linux_doctor: Path) -> None:
    result = _doctor()
    assert result.exit_code == 0, result.output
    assert "platform: ubuntu 24.04" in result.stdout
    assert "bubblewrap: ok" in result.stdout
    assert "linger: off" in result.stdout


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("state", ["locked", "unavailable"])
def test_doctor_reports_inaccessible_secrets_for_host_and_observability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: bool, state: str
) -> None:
    from sevn.secrets.backends import use_keyring

    _isolate(tmp_path, monkeypatch, backend="secret-service")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    _patch_probes(monkeypatch, {name: _constant(value) for name, value in _PROBES.items()})
    monkeypatch.setattr("sevn.runtime.installs.resolve", _fake_resolve)
    monkeypatch.setattr("sevn.secrets.probe_secret_service", _constant(state))
    ring = FakeKeyring(locked=state == "locked", unavailable=state == "unavailable")
    use_keyring(ring)
    try:
        body = _json(_doctor("--json", *(["--check"] if check else [])))
    finally:
        use_keyring(None)
    assert body["secrets_backend"] == f"secret-service ({state})"
    assert body["observability_exporter"] == f"secrets_{state}"
    assert body["observability_content"] == "off"
    if check:
        assert body["observability_check"] == f"secrets_{state}"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_doctor_json_keeps_existing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", platform)
    _patch_probes(monkeypatch, {name: _constant(value) for name, value in _PROBES.items()})
    monkeypatch.setattr("sevn.runtime.installs.resolve", _fake_resolve)
    body = _json(_doctor("--json"))
    for key, kind in _EXISTING_KEYS.items():
        assert key in body, key
        assert isinstance(body[key], kind), (key, body[key])
    assert body["secrets_backend"] == "age-file"
    for key in (*_LINUX_KEYS, "runtimes"):
        assert key in body, key


def test_doctor_on_macos_marks_linux_only_checks_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "darwin")

    def linux_only(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a Linux-only probe ran on macOS")

    _patch_probes(
        monkeypatch,
        {
            "probe_platform": _constant("macos 15.7"),
            "probe_service": _constant("not-installed"),
            "probe_bubblewrap": linux_only,
            "probe_display": linux_only,
            "probe_portals": linux_only,
            "probe_linger": linux_only,
        },
    )
    monkeypatch.setattr("sevn.runtime.installs.resolve", _fake_resolve)
    body = _json(_doctor("--json"))
    for key in ("bubblewrap", "display", "portals", "linger"):
        assert body[key] == "n/a", key
    assert body["service"] == "not-installed"


@pytest.fixture
def hanging_probes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[threading.Event]:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    release = threading.Event()

    def hang(*_args: object, **_kwargs: object) -> object:
        release.wait(10)
        return "late"

    _patch_probes(monkeypatch, dict.fromkeys(_PROBES, hang))
    monkeypatch.setattr("sevn.runtime.installs.resolve", hang)
    monkeypatch.setattr("sevn.secrets.probe_secret_service", hang)
    try:
        yield release
    finally:
        release.set()


def test_checks_time_out_without_raising(hanging_probes: threading.Event) -> None:
    started = time.monotonic()
    body = _json(_doctor("--json"))
    elapsed = time.monotonic() - started
    assert elapsed < 6.0, f"doctor took {elapsed:.1f}s; the checks must run within ~2 s together"
    for key in (*_LINUX_KEYS, "runtimes"):
        assert body[key] == "timeout", (key, body[key])
    assert body["secrets_backend"] == "age-file"


def test_check_errors_are_reported_not_raised(
    linux_doctor: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("probe exploded")

    _patch_probes(monkeypatch, dict.fromkeys(_PROBES, broken))
    body = _json(_doctor("--json"))
    for key in _LINUX_KEYS:
        assert str(body[key]).startswith("error"), (key, body[key])


# --- platform ----------------------------------------------------------------

_UBUNTU = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n'
_ARCH = 'NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\n'
_DEBIAN = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nVERSION_ID="12"\nID=debian\n'
_FEDORA = 'NAME="Fedora Linux"\nVERSION_ID=41\nID=fedora\n'


@pytest.mark.parametrize(
    ("os_release", "in_container", "expected"),
    [
        (_UBUNTU, False, "ubuntu 24.04"),
        (_ARCH, False, "arch"),
        (_DEBIAN, False, "debian"),
        (_FEDORA, False, "fedora"),
        (None, False, "linux"),
        ("", False, "linux"),
        (_UBUNTU, True, "container"),
        (_DEBIAN, True, "container"),
    ],
    ids=["ubuntu", "arch", "debian", "other-id", "missing", "empty", "ubuntu-ctr", "debian-ctr"],
)
def test_classify_platform(os_release: str | None, in_container: bool, expected: str) -> None:
    from sevn.system import classify_platform

    assert classify_platform(os_release, in_container=in_container) == expected


@pytest.mark.parametrize(
    ("marker", "expected"),
    [(".dockerenv", True), ("run/.containerenv", True), (None, False)],
)
def test_in_container_reads_marker_files(
    tmp_path: Path, marker: str | None, expected: bool
) -> None:
    from sevn.system import in_container

    if marker is not None:
        target = tmp_path / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    assert in_container(tmp_path) is expected


def test_probe_platform_reads_os_release(tmp_path: Path) -> None:
    from sevn.system import probe_platform

    release = tmp_path / "os-release"
    release.write_text(_UBUNTU, encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    assert probe_platform(os_release=release, root=root) == "ubuntu 24.04"
    (root / ".dockerenv").write_text("", encoding="utf-8")
    assert probe_platform(os_release=release, root=root) == "container"


# --- bubblewrap (W0.5 facts) -------------------------------------------------

_BWRAP_CASES = [
    (
        "bwrap: No permissions to create new namespace, likely because the kernel does not "
        "allow non-privileged user namespaces. See <https://deb.li/bubblewrap> or <file:///"
        "usr/share/doc/bubblewrap/README.Debian.gz>.",
        False,
        "userns-blocked",
    ),
    ("bwrap: No permissions to create a new namespace", True, "unavailable-in-container"),
    ("bwrap: Can't mount proc on /newroot/proc: Operation not permitted", True,
     "unavailable-in-container"),
    ("bwrap: Can't mount proc on /proc: Operation not permitted", True,
     "unavailable-in-container"),
    ("bwrap: setting up uid map: Permission denied", False, "userns-blocked"),
    ("bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted", False, "userns-blocked"),
]  # fmt: skip


@pytest.mark.parametrize(("stderr", "container", "expected"), _BWRAP_CASES)
def test_classify_bwrap_maps_known_failures(stderr: str, container: bool, expected: str) -> None:
    from sevn.system import classify_bwrap

    value = classify_bwrap(1, stderr, in_container=container)
    assert value.startswith(expected), value
    if expected == "userns-blocked":
        assert _USERNS_SYSCTL in value


def test_classify_bwrap_ok_and_unknown_failure() -> None:
    from sevn.system import classify_bwrap

    assert classify_bwrap(0, "", in_container=False) == "ok"
    assert classify_bwrap(0, "bwrap: warning noise", in_container=True) == "ok"
    unknown = classify_bwrap(1, "bwrap: something new went wrong", in_container=False)
    assert unknown.startswith("failed"), unknown
    assert unknown != "ok"


def _fake_bin(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_probe_bubblewrap_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.system import probe_bubblewrap

    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert probe_bubblewrap(in_container=False) == "missing"


def test_probe_bubblewrap_runs_the_sandbox_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.system import probe_bubblewrap

    bindir = tmp_path / "bin"
    seen = tmp_path / "argv.txt"
    # Succeeds only when called with 0020's argv shape, not a bare `bwrap --version`.
    _fake_bin(
        bindir,
        "bwrap",
        f'printf "%s\\n" "$@" > "{seen}"\n'
        'case " $* " in *" --unshare-all "*) ;; '
        '*) echo "bwrap: unexpected argv" >&2; exit 1;; esac\n'
        'case " $* " in *" --proc "*) exit 0;; esac\n'
        'echo "bwrap: unexpected argv" >&2\nexit 1',
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    assert probe_bubblewrap(in_container=False) == "ok"
    assert "--unshare-all" in seen.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(("stderr", "container", "expected"), _BWRAP_CASES[:3])
def test_probe_bubblewrap_classifies_real_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str, container: bool, expected: str
) -> None:
    from sevn.system import probe_bubblewrap

    bindir = tmp_path / "bin"
    message = tmp_path / "stderr.txt"
    message.write_text(stderr + "\n", encoding="utf-8")
    _fake_bin(bindir, "bwrap", f'cat "{message}" >&2\nexit 1')
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    assert probe_bubblewrap(in_container=container).startswith(expected)


def test_probe_bubblewrap_times_out_and_kills_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.system import probe_bubblewrap

    bindir = tmp_path / "bin"
    pidfile = tmp_path / "bwrap.pid"
    _fake_bin(bindir, "bwrap", f'echo $$ > "{pidfile}"\nexec sleep 30')
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    started = time.monotonic()
    assert probe_bubblewrap(in_container=False, timeout=0.5) == "timeout"
    assert time.monotonic() - started < 3.0
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 3
    alive = True
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            alive = False
            break
        time.sleep(0.05)
    if alive:
        os.kill(pid, signal.SIGKILL)
    assert not alive, "the timed-out bwrap child is still running"


# --- display, portals, linger, service ---------------------------------------


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"}, "wayland"),
        ({"WAYLAND_DISPLAY": "wayland-1"}, "wayland"),
        ({"DISPLAY": ":0"}, "x11"),
        ({}, "none"),
        ({"WAYLAND_DISPLAY": "", "DISPLAY": ""}, "none"),
    ],
    ids=["both", "wayland", "x11", "none", "empty"],
)
def test_classify_display(env: dict[str, str], expected: str) -> None:
    from sevn.system import classify_display

    assert classify_display(env) == expected


def test_probe_portals_lists_backends(tmp_path: Path) -> None:
    from sevn.system import probe_portals

    portals = tmp_path / "portals"
    assert probe_portals(portals_dir=portals) == "none"
    portals.mkdir()
    assert probe_portals(portals_dir=portals) == "none"
    for name in ("hyprland", "gtk"):
        (portals / f"{name}.portal").write_text("[portal]\n", encoding="utf-8")
    (portals / "README").write_text("not a portal", encoding="utf-8")
    assert probe_portals(portals_dir=portals) == "xdg-desktop-portal (gtk, hyprland)"


@pytest.fixture
def fake_runner() -> Iterator[FakeRunner]:
    from sevn.service.runner import use_runner

    runner = FakeRunner()
    use_runner(runner)
    try:
        yield runner
    finally:
        use_runner(None)


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [(0, "Linger=yes\n", "on"), (0, "Linger=no\n", "off"), (127, "", "unknown")],
)
def test_probe_linger_reads_loginctl(
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected: str,
) -> None:
    from sevn.system import probe_linger

    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("LOGNAME", "tester")
    fake_runner.on("loginctl", "show-user", returncode=returncode, stdout=stdout)
    assert probe_linger() == expected
    assert fake_runner.find("loginctl", "show-user"), fake_runner.argvs()
    assert all("enable-linger" not in argv for argv in fake_runner.argvs())


def test_probe_service_reports_the_d1_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_runner: FakeRunner
) -> None:
    from sevn.system import probe_service

    user = tmp_path / "user"
    unit = user / ".config" / "systemd" / "user" / "sevn.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Service]\nExecStart=/x serve\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    fake_runner.on(
        "systemctl",
        "--user",
        "show",
        "sevn.service",
        stdout="LoadState=loaded\nActiveState=active\nExecMainStatus=0\n",
    )
    assert probe_service() == "running"


# --- WV F3: unknown IDs fall back to the first known ID_LIKE (D13) ------------

_OMARCHY = 'NAME="Omarchy"\nID=omarchy\nID_LIKE=arch\nBUILD_ID=rolling\n'
_ENDEAVOUR = 'NAME="EndeavourOS"\nID="endeavouros"\nID_LIKE="arch"\n'
_POP = 'NAME="Pop!_OS"\nVERSION_ID="22.04"\nID=pop\nID_LIKE="ubuntu debian"\n'
_KALI = 'NAME="Kali GNU/Linux"\nVERSION_ID="2025.1"\nID=kali\nID_LIKE=debian\n'
_ROCKY = 'NAME="Rocky Linux"\nVERSION_ID="9.4"\nID="rocky"\nID_LIKE="rhel centos fedora"\n'


@pytest.mark.parametrize(
    ("os_release", "expected"),
    [
        (_OMARCHY, "arch"),
        (_ENDEAVOUR, "arch"),
        (_POP, "ubuntu"),
        (_KALI, "debian"),
    ],
    ids=["omarchy", "endeavouros", "pop-ubuntu-first", "kali"],
)
def test_classify_platform_falls_back_to_a_known_id_like(os_release: str, expected: str) -> None:
    from sevn.system import classify_platform

    assert classify_platform(os_release, in_container=False) == expected
    assert classify_platform(os_release, in_container=True) == "container"


@pytest.mark.parametrize(
    ("os_release", "expected"),
    [(_ROCKY, "rocky"), (_FEDORA, "fedora"), (_UBUNTU, "ubuntu 24.04"), (_ARCH, "arch")],
    ids=["unknown-id-like", "no-id-like", "known-id-wins", "arch"],
)
def test_classify_platform_keeps_ids_without_a_known_family(os_release: str, expected: str) -> None:
    from sevn.system import classify_platform

    assert classify_platform(os_release, in_container=False) == expected
