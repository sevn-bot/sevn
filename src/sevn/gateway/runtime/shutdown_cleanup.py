"""Gateway shutdown helpers for third-party resource-tracker gaps.

Module: sevn.gateway.runtime.shutdown_cleanup
Depends: gc, multiprocessing.synchronize (stdlib)

Exports:
    release_leaked_multiprocessing_semaphores — unlink and unregister named semaphores.
    reap_sevn_browsers_on_shutdown — terminate sevn-spawned Chrome on gateway stop (D6).
"""

from __future__ import annotations

import contextlib
import gc
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from loguru import logger

_MP_SEM_TYPES: tuple[Any, ...] | None = None


def _mp_semaphore_types() -> tuple[Any, ...]:
    """Return multiprocessing semaphore wrapper types when importable.

    Returns:
        tuple[type[object], ...]: ``SemLock`` / ``Semaphore`` classes, or empty.

    Examples:
        >>> isinstance(_mp_semaphore_types(), tuple)
        True
    """
    global _MP_SEM_TYPES
    if _MP_SEM_TYPES is not None:
        return _MP_SEM_TYPES
    try:
        from multiprocessing import BoundedSemaphore, Semaphore
        from multiprocessing.synchronize import SemLock
    except ImportError:
        _MP_SEM_TYPES = ()
    else:
        _MP_SEM_TYPES = (SemLock, Semaphore, BoundedSemaphore)
    return _MP_SEM_TYPES


def _semlock_names_from_gc() -> set[str]:
    """Collect named-semaphore paths still referenced in the interpreter.

    Returns:
        set[str]: Semaphore names registered with the resource tracker.

    Examples:
        >>> isinstance(_semlock_names_from_gc(), set)
        True
    """
    sem_types = _mp_semaphore_types()
    if not sem_types:
        return set()
    names: set[str] = set()
    for obj in gc.get_objects():
        with contextlib.suppress(Exception):
            if not isinstance(obj, sem_types):
                continue
            semlock = getattr(obj, "_semlock", obj)
            if type(semlock).__name__ != "SemLock":
                continue
            name = getattr(semlock, "name", None)
            if isinstance(name, str) and name:
                names.add(name)
    return names


def release_leaked_multiprocessing_semaphores() -> None:
    """Unlink and unregister named semaphores still referenced at gateway shutdown.

    Some optional dependencies create ``multiprocessing.Semaphore`` objects without
    running their stdlib finalizers before the resource-tracker subprocess exits.
    This mirrors :meth:`multiprocessing.synchronize.SemLock._cleanup` for each
    live name so shutdown does not emit ``resource_tracker`` leak warnings.

    Examples:
        >>> release_leaked_multiprocessing_semaphores() is None
        True
    """
    try:
        from multiprocessing.synchronize import SemLock
    except ImportError:
        return
    cleanup = getattr(SemLock, "_cleanup", None)
    if not callable(cleanup):
        return
    cleanup_fn = cast("Callable[[str], None]", cleanup)
    try:
        names = _semlock_names_from_gc()
    except Exception as exc:
        logger.debug("multiprocessing semaphore scan skipped: {}", exc)
        return
    if not names:
        return
    released = 0
    for name in names:
        with contextlib.suppress(Exception):
            cleanup_fn(name)
            released += 1
    if released:
        logger.debug(
            "released {} multiprocessing semaphore(s) at gateway shutdown",
            released,
        )


def reap_sevn_browsers_on_shutdown(content_root: Path) -> list[int]:
    """Terminate sevn-spawned Chrome processes at gateway shutdown (D6).

    Thin re-export of :func:`sevn.browser.lifecycle.reap_sevn_browsers_on_shutdown`
    so gateway shutdown helpers stay discoverable from this module.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        list[int]: PIDs processed from sevn-spawned registry rows.

    Examples:
        >>> import tempfile
        >>> reap_sevn_browsers_on_shutdown(Path(tempfile.mkdtemp()))
        []
    """
    from sevn.browser.lifecycle import (
        reap_sevn_browsers_on_shutdown as _reap,
    )

    return _reap(content_root)


__all__ = [
    "reap_sevn_browsers_on_shutdown",
    "release_leaked_multiprocessing_semaphores",
]
