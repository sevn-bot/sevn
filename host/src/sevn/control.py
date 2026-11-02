"""Where the host's unix control socket lives (plan 0055 WV fix, F1-F2).

``sevn serve`` also serves its app on a unix socket so the local CLI (``sevn probe``,
``sevn devices revoke``) reaches the host as a loopback session on any TCP bind. The
socket is ``<home>/run/control.sock`` when that path fits AF_UNIX's limit. Otherwise
it goes in a short private directory under the system temp dir, and
``<home>/run/control`` holds its path so clients can find it.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path

SOCKET_NAME = "control.sock"
POINTER_NAME = "control"
# ``sun_path`` holds 104 bytes on macOS and 108 on Linux, including the trailing NUL.
_PATH_LIMIT = 103 if sys.platform == "darwin" else 107


class ControlPathError(Exception):
    """No safe place for the control socket."""


def fits(path: Path) -> bool:
    return len(os.fsencode(str(path))) <= _PATH_LIMIT


def server_path(home: Path, run: Path) -> Path:
    """The path the host binds. Creates the short private directory when needed."""
    preferred = run / SOCKET_NAME
    if fits(preferred):
        return preferred
    tag = hashlib.sha256(os.fsencode(str(home.resolve()))).hexdigest()[:16]
    name = f"sevn-{os.getuid()}-{tag}"
    for base in (Path(tempfile.gettempdir()), Path("/tmp")):  # noqa: S108 — private 0700 dir
        candidate = base / name / SOCKET_NAME
        if fits(candidate):
            _private_dir(candidate.parent)
            return candidate
    raise ControlPathError("no short enough path for the control socket")


def client_path(run: Path) -> Path | None:
    """The live control socket for this home, if one exists (the pointer wins)."""
    pointer = run / POINTER_NAME
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            found = Path(text)
            return found if _is_socket(found) else None
    found = run / SOCKET_NAME
    return found if _is_socket(found) else None


def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.lstat().st_mode)
    except OSError:
        return False


def _private_dir(path: Path) -> None:
    """Create ``path`` 0700, or accept it only if it is ours and not reachable by others."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ControlPathError(f"{path} is not a directory owned by this user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ControlPathError(f"{path} is reachable by other users")
