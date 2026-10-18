"""Host filesystem layout."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _user_home() -> Path:
    return Path.home()


def _darwin() -> bool:
    return sys.platform == "darwin"


def _default_home() -> Path:
    if _darwin():
        return _user_home() / "Library" / "Application Support" / "sevn"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "sevn"
    return _user_home() / ".local" / "share" / "sevn"


def _logs_dir(home: Path, *, honor_home: bool) -> Path:
    if honor_home or not _darwin():
        return home / "logs"
    return _user_home() / "Library" / "Logs" / "sevn"


def _workspaces_dir(home: Path) -> Path:
    override = os.environ.get("SEVN_WORKSPACES")
    if override:
        return Path(override)
    if _darwin():
        return _user_home() / "Sevn"
    return home / "workspaces"


@dataclass(frozen=True, slots=True)
class Paths:
    """Directories and files owned by one host home."""

    home: Path
    db: Path
    run: Path
    logs: Path
    secrets_file: Path
    keys: Path
    workspaces: Path

    @classmethod
    def _build(cls, home: Path, *, honor_home: bool) -> Paths:
        return cls(
            home=home,
            db=home / "sevn.db",
            run=home / "run",
            logs=_logs_dir(home, honor_home=honor_home),
            secrets_file=home / "secrets.age",
            keys=home / "keys",
            workspaces=_workspaces_dir(home),
        )

    @classmethod
    def default(cls) -> Paths:
        """Platform defaults. ``SEVN_HOME`` is not consulted."""
        return cls._build(_default_home(), honor_home=False)

    @classmethod
    def from_env(cls) -> Paths:
        """Platform defaults with ``SEVN_HOME`` applied when it is set."""
        raw = os.environ.get("SEVN_HOME")
        if raw:
            return cls._build(Path(raw).expanduser(), honor_home=True)
        return cls._build(_default_home(), honor_home=False)
