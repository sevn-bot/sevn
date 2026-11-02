"""``deploy/install.sh`` (plan 0025 D2, W6) and the Linux docs it points at.

The default suite runs the script under ``/bin/sh`` in a sandbox: ``PATH`` holds
fake ``sudo``, ``apt-get``, ``pacman``, ``uv``, ``curl`` and ``sevn`` that only
record their argv, plus links to the POSIX utilities the host has. ``HOME`` is a
temp directory. Nothing is installed and no network is used. The real end-to-end
run (real ``uv``, a built wheel) is a live test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from support.archives import sha256
from support.repo import repo_root

_SCRIPT = repo_root() / "deploy" / "install.sh"
_APT = {"bubblewrap", "git", "curl", "ca-certificates", "libsecret-1-0"}
_PACMAN = {"bubblewrap", "git", "curl", "libsecret"}
_WHEEL = "sevn-1.2.3-py3-none-any.whl"
# POSIX utilities a POSIX sh installer may use. Missing ones are skipped.
_UTILITIES = (
    "awk", "basename", "cat", "chmod", "cp", "cut", "date", "dirname", "env", "expr",
    "find", "grep", "head", "id", "ln", "ls", "mkdir", "mktemp", "mv", "printf", "rm",
    "rmdir", "sed", "sh", "sha256sum", "shasum", "perl", "sleep", "sort", "tail", "tee",
    "test", "touch", "tr", "true", "false", "uname", "wc", "xargs", "tty", "readlink",
    "realpath", "dash", "bash",
)  # fmt: skip
_FAKE = """#!{python}
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": name, "argv": sys.argv[1:]}}) + "\\n")
{body}
"""
_SUDO = """
os.execvp(sys.argv[1], sys.argv[1:])
"""
_UV = """
args = sys.argv[1:]
if args[:3] == ["tool", "dir", "--bin"]:
    print(os.environ["FAKE_UV_BIN"])
"""
_CURL = """
args = sys.argv[1:]
url = next(a for a in args if a.startswith(("http://", "https://", "file://")))
out = None
for i, a in enumerate(args):
    if a in ("-o", "--output"):
        out = args[i + 1]
source = os.path.join(os.environ["FAKE_CURL_ROOT"], url.rstrip("/").rsplit("/", 1)[1])
if not os.path.isfile(source):
    sys.stderr.write("curl: (22) The requested URL returned error: 404\\n")
    sys.exit(22)
data = open(source, "rb").read()
if out is None:
    sys.stdout.buffer.write(data)
else:
    open(out, "wb").write(data)
"""
_SILENT = ""


@dataclass
class Sandbox:
    root: Path
    home: Path
    fakes: Path
    log: Path
    downloads: Path
    uv_bin: Path
    env: dict[str, str]

    def calls(self, tool: str | None = None) -> list[list[str]]:
        if not self.log.is_file():
            return []
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [row["argv"] for row in rows if tool is None or row["tool"] == tool]


def _write_fake(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(_FAKE.format(python=sys.executable, body=body), encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    if not _SCRIPT.is_file():
        pytest.fail("deploy/install.sh is missing")
    home = tmp_path / "home"
    home.mkdir()
    fakes = tmp_path / "fakes"
    utilities = tmp_path / "utilities"
    utilities.mkdir()
    for name in _UTILITIES:
        found = shutil.which(name)
        if found is not None:
            (utilities / name).symlink_to(found)
    uv_bin = home / ".local" / "bin"
    for name, body in (("sudo", _SUDO), ("uv", _UV), ("curl", _CURL), ("sevn", _SILENT)):
        _write_fake(fakes, name, body)
    _write_fake(uv_bin, "sevn", _SILENT)
    downloads = tmp_path / "release"
    downloads.mkdir()
    log = tmp_path / "calls.jsonl"
    env = {
        "HOME": str(home),
        "PATH": f"{fakes}{os.pathsep}{uv_bin}{os.pathsep}{utilities}",
        "FAKE_LOG": str(log),
        "FAKE_UV_BIN": str(uv_bin),
        "FAKE_CURL_ROOT": str(downloads),
        "SEVN_RELEASE_BASE": "https://example.invalid/sevn/releases/latest/download",
        "LANG": "C",
    }
    return Sandbox(tmp_path, home, fakes, log, downloads, uv_bin, env)


def _run(box: Sandbox, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["/bin/sh", str(_SCRIPT), *args],
        env=box.env,
        cwd=box.root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _local_wheel(box: Sandbox) -> Path:
    wheel = box.root / _WHEEL
    wheel.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    return wheel


def _packages(argv: list[str]) -> set[str]:
    return {word for word in argv if not word.startswith("-") and word not in {"install"}}


def _installs(box: Sandbox, manager: str) -> list[list[str]]:
    calls = box.calls(manager)
    if manager == "apt-get":
        return [argv for argv in calls if "install" in argv]
    return [argv for argv in calls if any(arg.startswith("-S") for arg in argv)]


# --- static checks -----------------------------------------------------------


def test_script_is_posix_sh_with_strict_mode() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "set -eu" in text
    completed = subprocess.run(  # noqa: S603
        ["/bin/sh", "-n", str(_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_shellcheck_clean() -> None:
    binary = shutil.which("shellcheck")
    if binary is None:
        pytest.skip("shellcheck is not installed")
    completed = subprocess.run(  # noqa: S603
        [binary, "-s", "sh", str(_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout


# --- package list per manager ------------------------------------------------


@pytest.mark.parametrize(("manager", "expected"), [("apt-get", _APT), ("pacman", _PACMAN)])
def test_package_list_per_manager(sandbox: Sandbox, manager: str, expected: set[str]) -> None:
    _write_fake(sandbox.fakes, manager, _SILENT)
    wheel = _local_wheel(sandbox)
    completed = _run(sandbox, "--no-service", "--wheel", str(wheel))
    assert completed.returncode == 0, completed.stderr
    installs = _installs(sandbox, manager)
    assert len(installs) == 1, sandbox.calls()
    assert _packages(installs[0]) == expected
    for name in expected:
        assert name in completed.stdout, "the package command is printed before it runs"
    if os.geteuid() != 0:
        sudo = sandbox.calls("sudo")
        assert sudo, "the package step runs through sudo"
        assert all(argv[0] == manager for argv in sudo), sudo


def test_without_a_known_manager_prints_packages_and_continues(sandbox: Sandbox) -> None:
    wheel = _local_wheel(sandbox)
    completed = _run(sandbox, "--no-service", "--wheel", str(wheel))
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout + completed.stderr
    assert "bubblewrap" in output
    assert sandbox.calls("sudo") == []
    assert any(argv[:2] == ["tool", "install"] for argv in sandbox.calls("uv"))


def test_no_system_deps_skips_the_package_step(sandbox: Sandbox) -> None:
    _write_fake(sandbox.fakes, "apt-get", _SILENT)
    wheel = _local_wheel(sandbox)
    completed = _run(sandbox, "--no-system-deps", "--no-service", "--wheel", str(wheel))
    assert completed.returncode == 0, completed.stderr
    assert sandbox.calls("apt-get") == []
    assert sandbox.calls("sudo") == []


# --- wheel, service, doctor --------------------------------------------------


def test_local_wheel_installs_and_runs_doctor(sandbox: Sandbox) -> None:
    wheel = _local_wheel(sandbox)
    completed = _run(sandbox, "--no-system-deps", "--no-service", "--wheel", str(wheel))
    assert completed.returncode == 0, completed.stderr
    uv = sandbox.calls("uv")
    installs = [argv for argv in uv if argv[:2] == ["tool", "install"]]
    assert len(installs) == 1, uv
    assert str(wheel) in installs[0]
    sevn = sandbox.calls("sevn")
    assert any(argv[:1] == ["doctor"] for argv in sevn), sevn
    assert not any(argv[:2] == ["service", "install"] for argv in sevn), sevn
    assert sandbox.calls("curl") == [], "uv is present, so nothing is downloaded"


def test_service_is_installed_with_the_home(sandbox: Sandbox) -> None:
    wheel = _local_wheel(sandbox)
    home = sandbox.root / "sevn-data"
    completed = _run(sandbox, "--no-system-deps", "--wheel", str(wheel), "--home", str(home))
    assert completed.returncode == 0, completed.stderr
    sevn = sandbox.calls("sevn")
    service = [argv for argv in sevn if argv[:2] == ["service", "install"]]
    assert len(service) == 1, sevn
    assert "--home" in service[0]
    assert service[0][service[0].index("--home") + 1] == str(home)
    doctor_at = next(i for i, argv in enumerate(sevn) if argv[:1] == ["doctor"])
    assert doctor_at > sevn.index(service[0])


def test_sudo_is_only_used_for_packages(sandbox: Sandbox) -> None:
    _write_fake(sandbox.fakes, "apt-get", _SILENT)
    wheel = _local_wheel(sandbox)
    completed = _run(sandbox, "--wheel", str(wheel))
    assert completed.returncode == 0, completed.stderr
    for argv in sandbox.calls("sudo"):
        assert argv[0] in {"apt-get", "pacman"}, argv


def test_never_edits_shell_profiles_without_a_tty(sandbox: Sandbox) -> None:
    wheel = _local_wheel(sandbox)
    completed = _run(sandbox, "--no-system-deps", "--no-service", "--wheel", str(wheel))
    assert completed.returncode == 0, completed.stderr
    assert not any(argv[:2] == ["tool", "update-shell"] for argv in sandbox.calls("uv"))
    for name in (".profile", ".bashrc", ".zshrc", ".bash_profile", ".config/fish/config.fish"):
        assert not (sandbox.home / name).exists(), name


# --- default wheel from the release (SHA256SUMS) ------------------------------


def _publish_release(box: Sandbox, *, tamper: bool) -> bytes:
    wheel = b"PK\x05\x06" + b"\x00" * 18
    (box.downloads / "SHA256SUMS").write_text(f"{sha256(wheel)}  {_WHEEL}\n", encoding="utf-8")
    (box.downloads / _WHEEL).write_bytes(wheel + (b"tampered" if tamper else b""))
    return wheel


def test_release_wheel_is_verified_against_sha256sums(sandbox: Sandbox) -> None:
    _publish_release(sandbox, tamper=False)
    completed = _run(sandbox, "--no-system-deps", "--no-service")
    assert completed.returncode == 0, completed.stderr
    fetched = [arg for argv in sandbox.calls("curl") for arg in argv if arg.startswith("https://")]
    base = sandbox.env["SEVN_RELEASE_BASE"]
    assert f"{base}/SHA256SUMS" in fetched
    assert f"{base}/{_WHEEL}" in fetched
    installs = [argv for argv in sandbox.calls("uv") if argv[:2] == ["tool", "install"]]
    assert len(installs) == 1
    assert any(arg.endswith(_WHEEL) for arg in installs[0])


def test_tampered_release_wheel_is_refused(sandbox: Sandbox) -> None:
    _publish_release(sandbox, tamper=True)
    completed = _run(sandbox, "--no-system-deps", "--no-service")
    assert completed.returncode != 0
    assert "checksum" in (completed.stdout + completed.stderr).lower()
    assert not any(argv[:2] == ["tool", "install"] for argv in sandbox.calls("uv"))
    assert sandbox.calls("sevn") == []


def test_unknown_option_is_refused(sandbox: Sandbox) -> None:
    completed = _run(sandbox, "--frobnicate")
    assert completed.returncode != 0
    assert sandbox.calls() == []


# --- live: the real thing ----------------------------------------------------


@pytest.mark.live
def test_live_install_with_a_local_wheel(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    dist = tmp_path / "dist"
    subprocess.run(  # noqa: S603
        [uv, "build", "--package", "sevn", "--wheel", "--out-dir", str(dist)],
        cwd=repo_root(),
        check=True,
        timeout=600,
    )
    wheel = next(dist.glob("sevn-*.whl"))
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "UV_TOOL_DIR": str(home / ".local" / "share" / "uv" / "tools"),
        "UV_TOOL_BIN_DIR": str(home / ".local" / "bin"),
    }
    completed = subprocess.run(  # noqa: S603
        ["/bin/sh", str(_SCRIPT), "--no-system-deps", "--no-service", "--wheel", str(wheel)],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    sevn = home / ".local" / "bin" / "sevn"
    doctor = subprocess.run(  # noqa: S603
        [str(sevn), "doctor", "--json"],
        env={**env, "SEVN_HOME": str(tmp_path / "data")},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stderr
    body: dict[str, Any] = json.loads(doctor.stdout)
    assert "platform" in body


# --- docs (W6.3) -------------------------------------------------------------

_LINUX_DOC = repo_root() / "docs" / "linux.md"


@pytest.mark.parametrize(
    "needle",
    [
        "deploy/install.sh",
        "loginctl enable-linger",
        "sevn secret migrate",
        "/etc/apparmor.d/bwrap",
        "kernel.apparmor_restrict_unprivileged_userns",
        "seccomp=unconfined",
        "systempaths=unconfined",
        "/proc/kcore",
        "full",
        "docker exec -it sevn",
    ],
)
def test_linux_doc_names_the_supported_setups(needle: str) -> None:
    assert needle in _LINUX_DOC.read_text(encoding="utf-8")


def test_linux_doc_never_recommends_weakening_the_kernel() -> None:
    text = _LINUX_DOC.read_text(encoding="utf-8")
    assert "apparmor_restrict_unprivileged_userns=0" not in text
    assert "chmod u+s" not in text
    assert "complain" not in text.lower() or "does not help" in text.lower()


@pytest.mark.parametrize(
    "needle", ["Ubuntu", "Omarchy", "Docker", "deploy/install.sh", "sevn runtimes install"]
)
def test_readme_install_section_covers_linux(needle: str) -> None:
    readme = (repo_root() / "README.md").read_text(encoding="utf-8")
    assert "## Install" in readme
    section = readme.split("## Install", 1)[1].split("\n## ", 1)[0]
    if needle == "sevn runtimes install":
        assert needle in readme
    else:
        assert needle in section
