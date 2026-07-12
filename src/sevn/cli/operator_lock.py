"""Advisory operator lock for mutating CLI operations (`specs/23-cli.md` §4.3).

The lock file records the holder PID. A crash releases ``flock(2)`` when file
descriptors close; **stale** locks are recovered when the recorded PID is dead or
the lock file is older than :data:`STALE_LOCK_TTL_SECONDS` (one hour).

Module: sevn.cli.operator_lock
Depends: fcntl, os, pathlib, contextlib, time

Exports:
    OperatorLockHeld — another process holds ``sevn-cli.lock``.
    operator_lock_path — ``{SEVN_HOME}/run/sevn-cli.lock``.
    lock_file_age_seconds — age of lock file from mtime.
    lock_file_appears_stale — heuristic for doctor hints.
    operator_lock — context manager acquiring the advisory lock.
"""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

from sevn.cli.errors import CliPreconditionError

STALE_LOCK_TTL_SECONDS: int = 3600


class OperatorLockHeld(CliPreconditionError):
    """Non-blocking lock acquisition failed — peer holds the lock."""

    def __init__(self, lock_path: Path, *, stale_hint: bool = False) -> None:
        """Record the lock file path for diagnostics.

        Args:
            lock_path (Path): Path passed to ``operator_lock``.
            stale_hint (bool): When True, message suggests ``sevn doctor`` / TTL recovery.

        Examples:
            >>> OperatorLockHeld(Path("/tmp/x")).args[0].startswith("another")
            True
        """
        suffix = ""
        if stale_hint:
            suffix = (
                "; lock file may be stale — run `sevn doctor` or wait for TTL recovery "
                "(mutating commands clear locks when the holder PID is dead)"
            )
        super().__init__(
            f"another sevn process holds the operator lock ({lock_path}{suffix})",
            exit_code=4,
        )


def operator_lock_path(sevn_home: Path) -> Path:
    """Return the advisory lock path under operator home.

    Args:
        sevn_home (Path): Resolved operator home (``sevn_home_dir()``).

    Returns:
        Path: ``{sevn_home}/run/sevn-cli.lock``.

    Examples:
        >>> operator_lock_path(Path("/tmp/h")).name
        'sevn-cli.lock'
    """
    return sevn_home / "run" / "sevn-cli.lock"


def lock_file_age_seconds(lock_path: Path) -> float:
    """Return lock file age in seconds from ``st_mtime``.

    Args:
        lock_path (Path): Lock file path.

    Returns:
        float: Seconds since mtime; ``0.0`` when the file does not exist.

    Examples:
        >>> lock_file_age_seconds(Path("/nonexistent")) == 0.0
        True
    """
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except OSError:
        return 0.0


def lock_file_appears_stale(lock_path: Path) -> bool:
    """Return True when the lock file is older than :data:`STALE_LOCK_TTL_SECONDS`.

    Args:
        lock_path (Path): Lock file path.

    Returns:
        bool: Whether the file exists and exceeds the TTL threshold.

    Examples:
        >>> lock_file_appears_stale(Path("/nonexistent"))
        False
    """
    if not lock_path.is_file():
        return False
    return lock_file_age_seconds(lock_path) > STALE_LOCK_TTL_SECONDS


def _pid_alive(pid: int) -> bool:
    """Return True when ``pid`` responds to signal 0.

    Args:
        pid (int): Process id read from the lock file.

    Returns:
        bool: Whether the process appears to be running.

    Examples:
        >>> _pid_alive(os.getpid())
        True
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_pid(lock_path: Path) -> int | None:
    """Parse PID written into the lock file, if any.

    Args:
        lock_path (Path): Lock file path.

    Returns:
        int | None: Parsed PID or None when unreadable.

    Examples:
        >>> _read_lock_pid(Path("/nonexistent")) is None
        True
    """
    try:
        raw = lock_path.read_text(encoding="utf-8").strip().split()
        if not raw:
            return None
        return int(raw[0])
    except (OSError, ValueError):
        return None


def _lock_held_by_dead_process(lock_path: Path) -> bool:
    """Return True when the lock file references a PID that is no longer running.

    Args:
        lock_path (Path): Lock file path.

    Returns:
        bool: Whether the recorded holder appears dead.

    Examples:
        >>> _lock_held_by_dead_process(Path("/nonexistent"))
        False
    """
    pid = _read_lock_pid(lock_path)
    if pid is None:
        return lock_file_appears_stale(lock_path)
    return not _pid_alive(pid)


def _try_acquire(lock_path: Path) -> int | None:
    """Open ``lock_path`` and take a non-blocking exclusive flock.

    Args:
        lock_path (Path): Lock file path.

    Returns:
        int | None: Open file descriptor when acquired; None when held by a peer.

    Examples:
        >>> isinstance(_try_acquire(Path("/tmp/x")), (int, type(None)))
        True
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(
        str(lock_path),
        os.O_CREAT | os.O_RDWR,
        0o600,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


@contextmanager
def operator_lock(sevn_home: Path) -> Generator[None, None, None]:
    """Acquire exclusive non-blocking advisory lock; exit ``4`` if held.

    Stale locks (dead PID or file age over :data:`STALE_LOCK_TTL_SECONDS`) are
    cleared once and acquisition is retried.

    Args:
        sevn_home (Path): Resolved operator home (``sevn_home_dir()``).

    Yields:
        None: While lock is held.

    Returns:
        Generator[None, None, None]: Context manager yielding while lock is held.

    Raises:
        OperatorLockHeld: When ``flock(LOCK_NB)`` fails after stale recovery.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> home = Path(tempfile.mkdtemp())
        >>> with operator_lock(home):
        ...     True
        True
    """
    lock_path = operator_lock_path(sevn_home)
    stale_hint = lock_file_appears_stale(lock_path)
    fd = _try_acquire(lock_path)
    if fd is None and _lock_held_by_dead_process(lock_path):
        with suppress(OSError):
            lock_path.unlink(missing_ok=True)
        fd = _try_acquire(lock_path)
    if fd is None:
        raise OperatorLockHeld(lock_path, stale_hint=stale_hint)
    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
