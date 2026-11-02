"""``sevn service`` as a launchd agent on macOS (plan 0025 D1)."""

from __future__ import annotations

import os
import plistlib
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from sevn.service import (
    InstallResult,
    ServiceError,
    ServiceStatus,
    UninstallResult,
    command_failure,
    plan_write,
    service_home,
    write_atomic,
)
from sevn.service.runner import execute

LABEL = "bot.sevn.host"
_TIMEOUT = 60.0
_LOG_LINES = 200
_STATE = re.compile(r"^\tstate = (.+)$", re.MULTILINE)
_LAST_EXIT = re.compile(r"^\tlast exit code = (-?\d+)", re.MULTILINE)


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path(home: Path) -> Path:
    return home / "logs" / "service.log"


def render_plist(executable: Path, home: Path, port: int | None = None) -> bytes:
    """The ``bot.sevn.host`` agent: ``executable serve`` with ``SEVN_HOME=home``."""
    program = [str(executable), "serve"]
    if port is not None:
        program += ["--port", str(port)]
    log = str(log_path(home))
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": program,
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "EnvironmentVariables": {"SEVN_HOME": str(home)},
            "StandardOutPath": log,
            "StandardErrorPath": log,
        },
        sort_keys=True,
    )


def _tail(path: Path, lines: int) -> str:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return "".join(deque(handle, maxlen=lines))


@dataclass(frozen=True, slots=True)
class LaunchdService:
    """The ``bot.sevn.host`` agent in the ``gui/<uid>`` domain."""

    plist: Path
    uid: int

    @classmethod
    def for_user(cls) -> LaunchdService:
        return cls(plist=plist_path(), uid=os.getuid())

    @property
    def path(self) -> Path:
        return self.plist

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    @property
    def target(self) -> str:
        return f"{self.domain}/{LABEL}"

    def install(
        self, executable: Path, home: Path, port: int | None, *, force: bool
    ) -> InstallResult:
        content = render_plist(executable, home, port)
        action = plan_write(self.plist, content, force=force)
        log_path(home).parent.mkdir(parents=True, exist_ok=True)
        if action == "unchanged":
            if not self._loaded():
                self._bootstrap()
            elif self.status().state == "running":
                # An upgrade keeps the plist but not the code: restart the running agent.
                self.restart()
            return InstallResult(path=self.plist, action=action)
        # Unload any earlier copy so the new plist is the one launchd runs; failure means
        # nothing was loaded.
        execute(["launchctl", "bootout", self.target], timeout=_TIMEOUT)
        write_atomic(self.plist, content)
        self._bootstrap()
        return InstallResult(path=self.plist, action=action)

    def uninstall(self) -> UninstallResult:
        if not os.path.lexists(self.plist):
            return UninstallResult(path=self.plist, removed=False)
        # A failure here means the agent was not loaded, which is fine.
        execute(["launchctl", "bootout", self.target], timeout=_TIMEOUT)
        self.plist.unlink(missing_ok=True)
        return UninstallResult(path=self.plist, removed=True)

    def status(self) -> ServiceStatus:
        if not os.path.lexists(self.plist):
            return ServiceStatus("not-installed")
        result = execute(["launchctl", "print", self.target], timeout=_TIMEOUT)
        if not result.ok:
            return ServiceStatus("stopped")
        state = _STATE.search(result.stdout)
        if state is not None and state.group(1).strip() == "running":
            return ServiceStatus("running")
        last = _LAST_EXIT.search(result.stdout)
        if last is None:
            return ServiceStatus("stopped")
        code = int(last.group(1))
        return ServiceStatus("stopped", 0) if code == 0 else ServiceStatus("failed", code)

    def restart(self) -> None:
        argv = ["launchctl", "kickstart", "-k", self.target]
        result = execute(argv, timeout=_TIMEOUT)
        if not result.ok:
            raise command_failure(argv, result.stderr, result.returncode)

    def logs(self, *, follow: bool) -> str:
        path = self._log_file()
        if not path.is_file():
            raise ServiceError(f"no service log at {path}")
        if not follow:
            return _tail(path, _LOG_LINES)
        argv = ["tail", "-n", str(_LOG_LINES), "-F", str(path)]
        result = execute(argv, capture=False)
        if not result.ok:
            raise command_failure(argv, result.stderr, result.returncode)
        return ""

    def _log_file(self) -> Path:
        """The installed agent's log, or the default home's when no agent says otherwise."""
        try:
            loaded: object = plistlib.loads(self.plist.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            loaded = None
        if isinstance(loaded, dict):
            configured = loaded.get("StandardOutPath")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(configured, str) and configured:
                return Path(configured)
        return log_path(service_home(None))

    def _loaded(self) -> bool:
        return execute(["launchctl", "print", self.target], timeout=_TIMEOUT).ok

    def _bootstrap(self) -> None:
        argv = ["launchctl", "bootstrap", self.domain, str(self.plist)]
        result = execute(argv, timeout=_TIMEOUT)
        if not result.ok:
            raise command_failure(argv, result.stderr, result.returncode)
