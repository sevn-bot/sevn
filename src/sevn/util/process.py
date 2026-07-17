"""Generic process liveness and terminate helpers (not Chrome-specific).

Module: sevn.util.process
Depends: contextlib, os, signal, time

Exports:
    pid_is_alive — whether a PID responds to ``signal 0``.
    terminate_pid — SIGTERM then optional SIGKILL with wait.

Examples:
    >>> terminate_pid(-1)
    False
"""

from __future__ import annotations

import contextlib
import os
import signal
import time


def pid_is_alive(pid: int) -> bool:
    """Return whether ``pid`` responds to ``os.kill(..., 0)``.

    Args:
        pid (int): Operating-system process id.

    Returns:
        bool: ``True`` when the process exists (and is signalable by this user).

    Examples:
        >>> pid_is_alive(os.getpid())
        True
        >>> pid_is_alive(0)
        False
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate_pid(pid: int, *, escalate: bool = True) -> bool:
    """Send ``SIGTERM`` to ``pid``, optionally escalate to ``SIGKILL`` after wait.

    Blocking (~5-6 s worst case); async callers must wrap with ``asyncio.to_thread``.

    Args:
        pid (int): Target process id.
        escalate (bool): When ``True``, ``SIGKILL`` if still alive after wait.

    Returns:
        bool: ``True`` when ``SIGTERM`` was delivered (process may still exit later).

    Examples:
        >>> terminate_pid(-1)
        False
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    for _ in range(50):
        if not pid_is_alive(pid):
            return True
        time.sleep(0.1)
    if escalate and pid_is_alive(pid):
        with contextlib.suppress(OSError, ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        for _ in range(20):
            if not pid_is_alive(pid):
                break
            time.sleep(0.05)
    return True


__all__ = [
    "pid_is_alive",
    "terminate_pid",
]
