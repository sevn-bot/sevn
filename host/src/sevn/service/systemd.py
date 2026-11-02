"""``sevn service`` on a systemd ``--user`` manager (plan 0025 D1)."""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from pathlib import Path

from sevn.service import (
    InstallResult,
    ServiceError,
    ServiceStatus,
    UninstallResult,
    command_failure,
    plan_write,
    write_atomic,
)
from sevn.service.runner import execute

UNIT_NAME = "sevn.service"
LINGER_TIMEOUT = 2.0
_TIMEOUT = 60.0
_LOG_LINES = "200"

_TEMPLATE = """\
[Unit]
Description=sevn host

[Service]
ExecStart={exec_start}
Environment={environment}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def _quote(value: str, *, command: bool) -> str:
    """One systemd word: ``%`` (and ``$`` on a command line) doubled, quoted when it would split."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ServiceError(
            f"cannot write a systemd unit for a path with a control character: {value!r}"
        )
    escaped = value.replace("%", "%%")
    if command:
        escaped = escaped.replace("$", "$$")
    if escaped == "" or any(char.isspace() or char in "\"'\\;" for char in escaped):
        escaped = '"' + escaped.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return escaped


def render_unit(executable: Path, home: Path, port: int | None = None) -> str:
    """The ``sevn.service`` unit text for ``executable serve`` with ``SEVN_HOME=home``."""
    words = [str(executable), "serve"]
    if port is not None:
        words += ["--port", str(port)]
    return _TEMPLATE.format(
        exec_start=" ".join(_quote(word, command=True) for word in words),
        environment=_quote(f"SEVN_HOME={home}", command=False),
    )


def unit_path() -> Path:
    """``$XDG_CONFIG_HOME/systemd/user/sevn.service``, defaulting to ``~/.config``."""
    config = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(config) if config and Path(config).is_absolute() else Path.home() / ".config"
    return base / "systemd" / "user" / UNIT_NAME


def _user() -> str:
    try:
        return getpass.getuser()
    except OSError:
        return str(os.getuid())


def _properties(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    return props


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def linger_hint(user: str) -> str:
    return (
        "linger is off, so the service stops when you log out. "
        f"To keep it running, run: loginctl enable-linger {user}"
    )


@dataclass(frozen=True, slots=True)
class SystemdService:
    """The ``sevn.service`` user unit."""

    unit: Path
    user: str

    @classmethod
    def for_user(cls) -> SystemdService:
        return cls(unit=unit_path(), user=_user())

    @property
    def path(self) -> Path:
        return self.unit

    def install(
        self, executable: Path, home: Path, port: int | None, *, force: bool
    ) -> InstallResult:
        content = render_unit(executable, home, port).encode()
        action = plan_write(self.unit, content, force=force)
        # An unchanged unit after an upgrade still runs the old code: restart it when it is
        # running (``enable --now`` below would leave it alone). A stopped one is not started
        # by the restart.
        restart = action == "replace" or (
            action == "unchanged" and self.status().state == "running"
        )
        if action != "unchanged":
            write_atomic(self.unit, content)
            self._systemctl("daemon-reload")
        if restart:
            # A running unit keeps its old ExecStart until restarted; a stopped one stays put.
            self._systemctl("try-restart", UNIT_NAME)
        self._systemctl("enable", "--now", UNIT_NAME)
        hints = (linger_hint(self.user),) if self.linger() is False else ()
        return InstallResult(path=self.unit, action=action, hints=hints)

    def uninstall(self) -> UninstallResult:
        if not self._installed():
            return UninstallResult(path=self.unit, removed=False)
        warnings: list[str] = []
        argv = ["systemctl", "--user", "disable", "--now", UNIT_NAME]
        result = execute(argv, timeout=_TIMEOUT)
        if not result.ok:
            warnings.append(command_failure(argv, result.stderr, result.returncode).message)
        self.unit.unlink(missing_ok=True)
        self._systemctl("daemon-reload")
        return UninstallResult(path=self.unit, removed=True, warnings=tuple(warnings))

    def status(self) -> ServiceStatus:
        if not self._installed():
            return ServiceStatus("not-installed")
        argv = [
            "systemctl",
            "--user",
            "show",
            UNIT_NAME,
            "--property=LoadState,ActiveState,SubState,ExecMainStatus",
        ]
        result = execute(argv, timeout=_TIMEOUT)
        if not result.ok:
            raise command_failure(argv, result.stderr, result.returncode)
        props = _properties(result.stdout)
        if props.get("LoadState") == "not-found":
            return ServiceStatus("not-installed")
        active = props.get("ActiveState", "")
        code = _int(props.get("ExecMainStatus"))
        if active in {"active", "reloading"}:
            return ServiceStatus("running")
        if active == "activating":
            if props.get("SubState") == "auto-restart":
                return ServiceStatus("failed", code)
            return ServiceStatus("running")
        if active == "failed":
            return ServiceStatus("failed", code)
        return ServiceStatus("stopped", code)

    def restart(self) -> None:
        self._systemctl("restart", UNIT_NAME)

    def logs(self, *, follow: bool) -> str:
        argv = ["journalctl", "--user", "-u", UNIT_NAME, "--no-pager", "-n", _LOG_LINES]
        if follow:
            argv.append("-f")
        result = execute(argv, capture=not follow)
        if not result.ok:
            raise command_failure(argv, result.stderr, result.returncode)
        return result.stdout

    def linger(self) -> bool | None:
        """Whether linger is on for this user; ``None`` when ``loginctl`` cannot tell."""
        argv = ["loginctl", "show-user", self.user, "--property=Linger"]
        result = execute(argv, timeout=LINGER_TIMEOUT)
        if not result.ok:
            return None
        value = _properties(result.stdout).get("Linger")
        if value == "yes":
            return True
        if value == "no":
            return False
        return None

    def _installed(self) -> bool:
        return os.path.lexists(self.unit)

    def _systemctl(self, *args: str) -> None:
        argv = ["systemctl", "--user", *args]
        result = execute(argv, timeout=_TIMEOUT)
        if not result.ok:
            raise command_failure(argv, result.stderr, result.returncode)
