"""Run the host as a per-user service (plan 0025 D1).

macOS uses a launchd agent (:mod:`sevn.service.launchd`), Linux a systemd ``--user`` unit
(:mod:`sevn.service.systemd`). Both go through :mod:`sevn.service.runner`, and neither ever
runs ``sudo`` or changes the user's linger setting.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sevn.paths import Paths

ServiceState = Literal["running", "stopped", "failed", "not-installed"]
WriteAction = Literal["create", "unchanged", "replace"]

UNSUPPORTED_MESSAGE = "sevn service supports macOS and Linux"


class ServiceError(Exception):
    """A service step failed. ``exit_code`` is what the CLI exits with."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class UnsupportedPlatformError(ServiceError):
    """The host is neither macOS nor Linux."""

    def __init__(self) -> None:
        super().__init__(UNSUPPORTED_MESSAGE, exit_code=2)


class UnitConflictError(ServiceError):
    """A unit or plist with other content is already installed and ``--force`` was not given."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} already exists with other content; pass --force to replace it")
        self.path = path


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    state: ServiceState
    exit_code: int | None = None

    def to_json(self) -> dict[str, str | int | None]:
        return {"state": self.state, "exit_code": self.exit_code}


@dataclass(frozen=True, slots=True)
class InstallResult:
    path: Path
    action: WriteAction
    hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UninstallResult:
    path: Path
    removed: bool
    warnings: tuple[str, ...] = ()


class ServiceManager(Protocol):
    """The operations ``sevn service`` exposes, for one platform's service manager."""

    @property
    def path(self) -> Path: ...

    def install(
        self, executable: Path, home: Path, port: int | None, *, force: bool
    ) -> InstallResult: ...

    def uninstall(self) -> UninstallResult: ...

    def status(self) -> ServiceStatus: ...

    def restart(self) -> None: ...

    def logs(self, *, follow: bool) -> str: ...


def manager() -> ServiceManager:
    """The service manager for this platform; raises :class:`UnsupportedPlatformError`."""
    platform = sys.platform
    if platform == "darwin":
        from sevn.service.launchd import LaunchdService

        return LaunchdService.for_user()
    if platform.startswith("linux"):
        from sevn.service.systemd import SystemdService

        return SystemdService.for_user()
    raise UnsupportedPlatformError


def service_home(home: Path | None) -> Path:
    """The absolute ``SEVN_HOME`` the service runs with: ``--home`` or the current default."""
    chosen = Paths.from_env().home if home is None else home
    return chosen.expanduser().resolve()


def sevn_executable() -> Path:
    """The absolute path of the ``sevn`` console script that is running (or the one on PATH).

    Symlinks are kept, so a ``uv tool`` shim keeps working after an upgrade.
    """
    candidates: list[Path] = []
    if sys.argv and Path(sys.argv[0]).name == "sevn":
        candidates.append(Path(sys.argv[0]))
    candidates.append(Path(sys.executable).parent / "sevn")
    found = shutil.which("sevn")
    if found is not None:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return Path(os.path.abspath(candidate))
    raise ServiceError(
        "cannot find the sevn executable; install sevn (for example with `uv tool install`)"
    )


def plan_write(path: Path, content: bytes, *, force: bool) -> WriteAction:
    """Decide how to install ``content`` at ``path``; raises :class:`UnitConflictError`."""
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        return "create"
    if existing == content:
        return "unchanged"
    if not force:
        raise UnitConflictError(path)
    return "replace"


def write_atomic(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` through a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        temp.chmod(0o644)
        temp.replace(path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def command_failure(argv: list[str], stderr: str, returncode: int) -> ServiceError:
    detail = stderr.strip() or f"exit code {returncode}"
    return ServiceError(f"`{' '.join(argv)}` failed: {detail}")
