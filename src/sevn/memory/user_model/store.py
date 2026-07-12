"""Atomic JSON persistence for ``user_model.json`` (`specs/32-memory-honcho.md` §2.2).

Module: sevn.memory.user_model.store
Depends: json, os, tempfile, threading, hashlib, pathlib

Exports:
    UserModelStore — load/save with per-root process lock + atomic rename.

Examples:
    >>> from sevn.memory.user_model.store import UserModelStore
    >>> UserModelStore
    <class 'sevn.memory.user_model.store.UserModelStore'>
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

from sevn.memory.user_model.models import UserProfile

_COMMIT_LOCKS: Final[dict[str, threading.Lock]] = {}
_GLOBAL_LOCK: Final[threading.Lock] = threading.Lock()


def _norm_root(workspace_root: str) -> str:
    """Return a stable dict key for ``workspace_root``.

    Args:
        workspace_root (str): Workspace filesystem root.

    Returns:
        str: Resolved absolute path string.

    Examples:
        >>> isinstance(_norm_root("."), str)
        True
    """

    return str(Path(workspace_root).expanduser().resolve())


def _workspace_lock(workspace_root: str) -> threading.Lock:
    """Return a process-wide lock for ``workspace_root`` (`specs/32-memory-honcho.md` §4.1).

    Args:
        workspace_root (str): Workspace filesystem root.

    Returns:
        threading.Lock: Shared lock instance for that root.

    Examples:
        >>> isinstance(_workspace_lock("."), type(threading.Lock()))
        True
    """

    key = _norm_root(workspace_root)
    with _GLOBAL_LOCK:
        lock = _COMMIT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _COMMIT_LOCKS[key] = lock
        return lock


def _default_workspace_id(workspace_root: str) -> str:
    """Derive a stable opaque ``workspace_id`` from the root path.

    Args:
        workspace_root (str): Workspace filesystem root.

    Returns:
        str: Short hex digest suitable for ``UserProfile.workspace_id``.

    Examples:
        >>> len(_default_workspace_id(".")) == 16
        True
    """

    digest = sha256(_norm_root(workspace_root).encode("utf-8")).hexdigest()
    return digest[:16]


def _profile_path(workspace_root: str) -> Path:
    """Return the absolute ``user_model.json`` path for ``workspace_root``.

    Args:
        workspace_root (str): Workspace filesystem root.

    Returns:
        Path: Absolute ``.sevn/user_model.json`` path.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.memory.user_model.store import _profile_path
        >>> p = _profile_path("/tmp")
        >>> p.name
        'user_model.json'
    """

    return Path(workspace_root).expanduser().resolve() / ".sevn" / "user_model.json"


def _atomic_write_bytes(final_path: Path, payload: bytes) -> None:
    """Write bytes via temp file + ``os.replace``.

    Args:
        final_path (Path): Destination path.
        payload (bytes): UTF-8 JSON payload.

    Returns:
        None: Always.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "out.json"
        >>> _atomic_write_bytes(p, b"{}")
        >>> p.read_bytes()
        b'{}'
    """

    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=final_path.parent,
        prefix=".user_model-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_name, final_path)
    except OSError:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


class UserModelStore:
    """Atomic JSON persistence under ``workspace/.sevn/user_model.json``."""

    def load(self, workspace_root: str) -> UserProfile:
        """Load profile or return an empty shell when the file is absent.

        Args:
            workspace_root (str): Workspace filesystem root.

        Returns:
            UserProfile: Parsed profile or an empty in-memory shell.

        Examples:
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from sevn.memory.user_model.store import UserModelStore
            >>> with TemporaryDirectory() as d:
            ...     p = Path(d).resolve()
            ...     s = UserModelStore()
            ...     prof = s.load(str(p))
            ...     prof.facts == []
            True
        """

        path = _profile_path(workspace_root)
        wid = _default_workspace_id(workspace_root)
        if not path.is_file():
            return UserProfile(
                workspace_id=wid,
                updated_at=datetime.now(tz=UTC),
                schema_version=1,
                facts=[],
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        prof = UserProfile.model_validate(raw)
        if not prof.workspace_id:
            return prof.model_copy(update={"workspace_id": wid})
        return prof

    def save(self, workspace_root: str, profile: UserProfile) -> None:
        """Write via temp file + rename; callers should hold the workspace lock.

        Args:
            workspace_root (str): Workspace filesystem root.
            profile (UserProfile): Profile snapshot to persist.

        Returns:
            None: Always.

        Examples:
            >>> from datetime import UTC, datetime
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from sevn.memory.user_model.models import UserProfile
            >>> from sevn.memory.user_model.store import UserModelStore
            >>> with TemporaryDirectory() as d:
            ...     root = Path(d).resolve()
            ...     prof = UserProfile(workspace_id="x", updated_at=datetime.now(tz=UTC), facts=[])
            ...     UserModelStore().save(str(root), prof)
            ...     (root / ".sevn" / "user_model.json").is_file()
            True
        """

        path = _profile_path(workspace_root)
        wid = _default_workspace_id(workspace_root)
        to_write = profile.model_copy(
            update={
                "workspace_id": profile.workspace_id or wid,
                "updated_at": datetime.now(tz=UTC),
            },
        )
        blob = to_write.model_dump_json(indent=2).encode("utf-8")
        lock = _workspace_lock(workspace_root)
        with lock:
            _atomic_write_bytes(path, blob)


__all__ = ["UserModelStore"]
