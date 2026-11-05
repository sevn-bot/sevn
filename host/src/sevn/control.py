"""Where the host's unix control socket lives (plan 0055 WV fix, F1-F2).

``sevn serve`` also serves its app on a unix socket so the local CLI (``sevn probe``,
``sevn devices revoke``) reaches the host as a loopback session on any TCP bind. The
socket is ``<home>/run/control.sock`` when that path fits AF_UNIX's limit. Otherwise
it goes in a fresh private directory with a random name under the system temp dir,
and ``<home>/run/control`` holds its path so clients can find it.

Clients send the loopback token over this socket, so they trust it only when the socket
and its directory belong to this user and the directory is closed to everyone else
(WV F4). A pointer that fails the check is ignored, never replaced by another path.
"""

from __future__ import annotations

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
    """The path the host binds. Makes a fresh private directory when ``run`` is too deep."""
    del home  # the fallback name is random, not derived from the home
    preferred = run / SOCKET_NAME
    if fits(preferred):
        return preferred
    prefix = f"sevn-{os.getuid()}-"
    for base in (Path(tempfile.gettempdir()), Path("/tmp")):  # noqa: S108 — 0700 mkdtemp
        # ``mkdtemp`` adds 8 random characters and creates the directory 0700.
        if fits(base / (prefix + "x" * 8) / SOCKET_NAME):
            created = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
            if not trusted_dir(created):
                raise ControlPathError(f"{created} is not private to this user")
            return created / SOCKET_NAME
    raise ControlPathError("no short enough path for the control socket")


def client_path(run: Path) -> Path | None:
    """The trusted control socket for this home, if any. A pointer, when present, decides."""
    pointer = run / POINTER_NAME
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        found = Path(text) if text else None
        return found if found is not None and trusted_socket(found) else None
    found = run / SOCKET_NAME
    return found if trusted_socket(found) else None


def trusted_socket(path: Path) -> bool:
    """A unix socket owned by this user, in a directory only this user can reach."""
    try:
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        return False
    return trusted_dir(path.parent)


def trusted_dir(path: Path) -> bool:
    """A real directory (not a symlink) owned by this user with no group/other bits."""
    try:
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        return False
    return stat.S_IMODE(info.st_mode) & 0o077 == 0
