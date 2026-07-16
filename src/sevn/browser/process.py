"""Chrome process helpers: identity, lock clear, and reap (no CDP types).

Module: sevn.browser.process
Depends: contextlib, os, subprocess, pathlib, sevn.util.process

Owns convention-11 profile identity checks and Chrome lock/reap so
:mod:`sevn.browser.lifecycle` stays a thin spawn/pool layer. Generic
``pid_is_alive`` / ``terminate_pid`` live in :mod:`sevn.util.process`
(re-exported via ``__all__`` for Chrome-path callers).

Exports:
    clear_profile_singleton_locks — delete Chrome singleton/port lockfiles.
    pid_matches_sevn_chrome_profile — cmdline identity check before kill.
    terminate_sevn_chrome — kill sevn Chrome for a profile (convention 11).
    reap_stale_sevn_chrome — kill sevn-spawned Chrome for one profile + clear locks.
    reap_sevn_browsers_on_shutdown — terminate all sevn-spawned browsers (D6).

Examples:
    >>> terminate_pid(-1)
    False
"""

from __future__ import annotations

import contextlib
import re
import subprocess  # nosec B404
from pathlib import Path
from typing import Final

from sevn.util.process import pid_is_alive, terminate_pid

_USER_DATA_DIR_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)--user-data-dir=([^\s]+)",
)

_PROFILE_LOCK_FILES: Final[tuple[str, ...]] = (
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "DevToolsActivePort",
)


def _read_pid_cmdline(pid: int) -> str:
    """Best-effort process command line for ``pid`` (Linux ``/proc`` or ``ps``).

    Args:
        pid (int): Operating-system process id.

    Returns:
        str: Command line text, or empty when unreadable.

    Examples:
        >>> _read_pid_cmdline(0)
        ''
    """
    if pid <= 0:
        return ""
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.is_file():
        try:
            return (
                proc_cmdline.read_bytes()
                .replace(b"\x00", b" ")
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )
        except OSError:
            return ""
    try:
        completed = subprocess.run(  # nosec B603 B607 — fixed argv, no shell
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def _cmdline_user_data_dir(cmdline: str) -> str | None:
    """Return the ``--user-data-dir`` argv value from ``cmdline``, if present.

    Args:
        cmdline (str): Process command line (space-separated).

    Returns:
        str | None: Exact ``user-data-dir`` path token, or ``None``.

    Examples:
        >>> _cmdline_user_data_dir("chrome --user-data-dir=/tmp/a --headless")
        '/tmp/a'
        >>> _cmdline_user_data_dir("chrome --headless") is None
        True
    """
    match = _USER_DATA_DIR_RE.search(cmdline)
    return match.group(1) if match else None


def _cmdline_is_chrome_family(cmdline: str) -> bool:
    """Return whether ``cmdline`` looks like Chrome, Chromium, or Brave.

    Args:
        cmdline (str): Process command line (space-separated).

    Returns:
        bool: ``True`` when the binary path mentions a supported engine.

    Examples:
        >>> _cmdline_is_chrome_family("/usr/bin/brave-browser --headless")
        True
        >>> _cmdline_is_chrome_family("/usr/bin/firefox --profile /tmp/p")
        False
    """
    lowered = cmdline.lower()
    return "chrome" in lowered or "chromium" in lowered or "brave" in lowered


def pid_matches_sevn_chrome_profile(pid: int, profile_dir: Path) -> bool:
    """Return whether ``pid`` still looks like Chrome/Brave for ``profile_dir`` (convention 11).

    Fail closed: when the cmdline cannot be read, returns ``False`` so we never
    SIGTERM/SIGKILL an unverified PID (operator Chrome / PID reuse). Matches
    ``--user-data-dir=<profile>`` as a full argv token so prefix profiles
    (``…/a`` vs ``…/ab``) do not cross-match. Accepts Chrome, Chromium, and
    Brave (``brave-browser``, ``Brave Browser.app``, etc.).

    Args:
        pid (int): Candidate process id from the session registry.
        profile_dir (Path): Expected ``--user-data-dir`` for this session.

    Returns:
        bool: ``True`` when cmdline mentions Chrome/Chromium/Brave and this profile path.

    Examples:
        >>> pid_matches_sevn_chrome_profile(0, Path("/tmp/p"))
        False
    """
    if pid <= 0:
        return False
    try:
        needle = str(profile_dir.expanduser().resolve())
    except OSError:
        needle = str(profile_dir)
    cmdline = _read_pid_cmdline(pid)
    if not cmdline:
        return False
    if not _cmdline_is_chrome_family(cmdline):
        return False
    user_data = _cmdline_user_data_dir(cmdline)
    if user_data is None:
        return False
    try:
        return Path(user_data).expanduser().resolve() == Path(needle)
    except OSError:
        return user_data == needle


def clear_profile_singleton_locks(profile_dir: Path) -> None:
    """Delete Chrome singleton and DevTools port lockfiles under ``profile_dir``.

    Args:
        profile_dir (Path): Chrome ``user-data-dir`` for this session only.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _ = (d / "SingletonLock").write_text("x", encoding="utf-8")
        >>> clear_profile_singleton_locks(d)
        >>> (d / "SingletonLock").exists()
        False
    """
    for name in _PROFILE_LOCK_FILES:
        with contextlib.suppress(OSError):
            (profile_dir / name).unlink()


def terminate_sevn_chrome(
    pid: int,
    profile_dir: Path | None,
    *,
    escalate: bool = True,
) -> bool:
    """Terminate a sevn-spawned Chrome PID for ``profile_dir`` (convention 11).

    When ``profile_dir`` is set, refuses to signal unless the cmdline still looks
    like sevn Chrome for that profile. When ``profile_dir`` is ``None``, only
    checks liveness then terminates (caller already validated identity).

    Args:
        pid (int): Recorded Chrome process id.
        profile_dir (Path | None): Profile directory to match, or ``None``.
        escalate (bool): Pass through to :func:`terminate_pid`.

    Returns:
        bool: ``True`` when a terminate signal was attempted.

    Examples:
        >>> terminate_sevn_chrome(-1, None)
        False
    """
    if pid <= 0 or not pid_is_alive(pid):
        return False
    if profile_dir is not None and not pid_matches_sevn_chrome_profile(pid, profile_dir):
        return False
    return terminate_pid(pid, escalate=escalate)


def reap_stale_sevn_chrome(
    content_root: Path,
    session_id: str,
    profile_dir: Path,
) -> None:
    """Kill a sevn-spawned Chrome for this profile (if live) and clear lockfiles (D1).

    Only acts on a registry PID with ``spawned_by_sevn=True`` whose recorded
    ``profile_dir`` matches ``profile_dir`` (convention 11). Never signals
    operator Chrome or another profile's process. When identity check refuses
    the kill, leaves the registry row intact (does not clear locks under a live
    foreign Chrome).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        profile_dir (Path): Target profile directory about to be spawned into.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.isfunction(reap_stale_sevn_chrome)
        True
    """
    from sevn.browser.registry import read_registry

    row = read_registry(content_root, session_id)
    if (
        row is not None
        and row.spawned_by_sevn
        and row.pid is not None
        and row.pid > 0
        and row.profile_dir
    ):
        try:
            recorded = Path(row.profile_dir).expanduser().resolve()
            target = profile_dir.expanduser().resolve()
        except OSError:
            recorded = Path(row.profile_dir)
            target = profile_dir
        if recorded == target:
            # Identity refuse → leave registry; still clear locks only when we
            # successfully terminate or the PID is already dead.
            if not pid_is_alive(row.pid):
                clear_profile_singleton_locks(profile_dir)
                return
            if not pid_matches_sevn_chrome_profile(row.pid, profile_dir):
                return
            terminate_sevn_chrome(row.pid, profile_dir, escalate=True)
    clear_profile_singleton_locks(profile_dir)


def reap_sevn_browsers_on_shutdown(content_root: Path) -> list[int]:
    """Terminate all sevn-spawned browsers recorded under ``content_root`` (D6).

    Scans ``.sevn/browser-sessions/*.json``, signals each ``spawned_by_sevn``
    PID with ``SIGTERM`` (when alive and identity matches), and clears the
    registry entry. Identity mismatches leave the registry intact so the next
    spawn does not clear locks under a live foreign Chrome.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        list[int]: PIDs processed from sevn-spawned registry rows.

    Examples:
        >>> import tempfile
        >>> reap_sevn_browsers_on_shutdown(Path(tempfile.mkdtemp()))
        []
    """
    from sevn.browser.registry import clear_registry, read_registry

    sessions_dir = content_root / ".sevn" / "browser-sessions"
    if not sessions_dir.is_dir():
        return []
    processed: list[int] = []
    for path in sorted(sessions_dir.glob("*.json")):
        session_id = path.stem
        row = read_registry(content_root, session_id)
        if row is None or not row.spawned_by_sevn or row.pid is None or row.pid <= 0:
            continue
        pid = row.pid
        processed.append(pid)
        if pid_is_alive(pid):
            profile = Path(row.profile_dir) if row.profile_dir else None
            if profile is None or not pid_matches_sevn_chrome_profile(pid, profile):
                # Live PID we cannot verify — leave registry so spawn won't
                # delete SingletonLock under operator Chrome.
                continue
            terminate_sevn_chrome(pid, profile, escalate=True)
        clear_registry(content_root, session_id)
        if row.profile_dir:
            with contextlib.suppress(OSError):
                clear_profile_singleton_locks(Path(row.profile_dir))
    return processed


__all__ = [
    "clear_profile_singleton_locks",
    "pid_is_alive",
    "pid_matches_sevn_chrome_profile",
    "reap_sevn_browsers_on_shutdown",
    "reap_stale_sevn_chrome",
    "terminate_pid",
    "terminate_sevn_chrome",
]
