"""Persisted browser session registry under ``.sevn/browser-sessions/``.

Module: sevn.browser.registry
Depends: contextlib, json, os, pathlib, tempfile, dataclasses

Owns registry row shape and atomic read/write/clear so :mod:`sevn.browser.process`
and :mod:`sevn.browser.lifecycle` never import :mod:`sevn.skills`.

Exports:
    BrowserSessionRegistry — persisted registry row for one gateway session.
    clear_registry — remove the registry file for a session.
    normalise_session_id — filesystem-safe session id segment.
    read_registry — load registry JSON for a session.
    registry_path — path to ``.sevn/browser-sessions/<session_id>.json``.
    write_registry — atomic JSON write for a session registry row.

Examples:
    >>> DEFAULT_SESSION_ID
    'default'
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path  # noqa: TC003
from typing import Final

DEFAULT_SESSION_ID: Final[str] = "default"


@dataclass(frozen=True)
class BrowserSessionRegistry:
    """Persisted browser session metadata under ``.sevn/browser-sessions/`` (D3)."""

    pid: int | None
    cdp_url: str
    cdp_port: int
    profile_dir: str
    headless: bool
    spawned_by_sevn: bool
    last_used_at: str
    active_target_id: str | None = None
    headless_persistent: bool = False


def normalise_session_id(session_id: str | None) -> str:
    """Return a filesystem-safe session id segment (D1 fallback ``default``).

    Args:
        session_id (str | None): Gateway session id or ``None``.

    Returns:
        str: Non-empty session key.

    Examples:
        >>> normalise_session_id("")
        'default'
        >>> normalise_session_id("web:abc")
        'web:abc'
    """
    text = (session_id or "").strip()
    return text or DEFAULT_SESSION_ID


def _registry_dir(content_root: Path) -> Path:
    """Return ``<content_root>/.sevn/browser-sessions`` directory path.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Registry directory (may not exist yet).

    Examples:
        >>> import tempfile
        >>> d = _registry_dir(Path(tempfile.mkdtemp()))
        >>> d.name
        'browser-sessions'
    """
    return content_root / ".sevn" / "browser-sessions"


def registry_path(content_root: Path, session_id: str) -> Path:
    """Return the registry JSON path for ``session_id``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        Path: ``.sevn/browser-sessions/<session_id>.json``.

    Examples:
        >>> import tempfile
        >>> p = registry_path(Path(tempfile.mkdtemp()), "s1")
        >>> p.suffix
        '.json'
    """
    sid = normalise_session_id(session_id)
    return _registry_dir(content_root) / f"{sid}.json"


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON via temp file + ``os.replace``.

    Args:
        path (Path): Destination file path.
        payload (dict[str, object]): Serializable registry payload.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "reg.json"
        >>> _atomic_write_json(p, {"cdp_url": "http://127.0.0.1:9222"})
        >>> json.loads(p.read_text(encoding="utf-8"))["cdp_url"]
        'http://127.0.0.1:9222'
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".browser-session-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _registry_from_dict(data: dict[str, object]) -> BrowserSessionRegistry:
    """Coerce a decoded JSON dict into :class:`BrowserSessionRegistry`.

    Args:
        data (dict[str, object]): Raw registry JSON object.

    Returns:
        BrowserSessionRegistry: Parsed row.

    Examples:
        >>> row = _registry_from_dict({"cdp_url": "http://127.0.0.1:1", "cdp_port": 1,
        ...     "profile_dir": "/p", "headless": False, "spawned_by_sevn": True,
        ...     "last_used_at": "2026-01-01T00:00:00+00:00"})
        >>> row.cdp_port
        1
    """
    pid_raw = data.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) else None
    port_raw = data.get("cdp_port", 0)
    cdp_port = int(port_raw) if isinstance(port_raw, int) else 0
    active = data.get("active_target_id")
    active_target_id = active if isinstance(active, str) and active.strip() else None
    return BrowserSessionRegistry(
        pid=pid,
        cdp_url=str(data.get("cdp_url", "")),
        cdp_port=cdp_port,
        profile_dir=str(data.get("profile_dir", "")),
        headless=bool(data.get("headless", False)),
        spawned_by_sevn=bool(data.get("spawned_by_sevn", False)),
        last_used_at=str(data.get("last_used_at", "")),
        active_target_id=active_target_id,
        headless_persistent=bool(data.get("headless_persistent", False)),
    )


def read_registry(content_root: Path, session_id: str) -> BrowserSessionRegistry | None:
    """Load registry JSON for ``session_id`` when present.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        BrowserSessionRegistry | None: Parsed row or ``None`` when missing.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> read_registry(root, "missing") is None
        True
    """
    path = registry_path(content_root, session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _registry_from_dict(data)


def write_registry(content_root: Path, session_id: str, row: BrowserSessionRegistry) -> None:
    """Atomically persist registry JSON for ``session_id``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        row (BrowserSessionRegistry): Registry payload.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from datetime import UTC, datetime
        >>> root = Path(tempfile.mkdtemp())
        >>> row = BrowserSessionRegistry(
        ...     pid=1, cdp_url="http://127.0.0.1:9333", cdp_port=9333,
        ...     profile_dir="/tmp/p", headless=False, spawned_by_sevn=True,
        ...     last_used_at=datetime.now(tz=UTC).isoformat(),
        ... )
        >>> write_registry(root, "s1", row)
        >>> read_registry(root, "s1") is not None
        True
    """
    path = registry_path(content_root, session_id)
    payload: dict[str, object] = dict(asdict(row))
    _atomic_write_json(path, payload)


def clear_registry(content_root: Path, session_id: str) -> None:
    """Remove the registry file for ``session_id`` when it exists.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from datetime import UTC, datetime
        >>> root = Path(tempfile.mkdtemp())
        >>> row = BrowserSessionRegistry(
        ...     pid=None, cdp_url="", cdp_port=0, profile_dir="/p",
        ...     headless=False, spawned_by_sevn=False,
        ...     last_used_at=datetime.now(tz=UTC).isoformat(),
        ... )
        >>> write_registry(root, "s1", row)
        >>> clear_registry(root, "s1")
        >>> read_registry(root, "s1") is None
        True
    """
    path = registry_path(content_root, session_id)
    with contextlib.suppress(OSError):
        path.unlink()


__all__ = [
    "DEFAULT_SESSION_ID",
    "BrowserSessionRegistry",
    "clear_registry",
    "normalise_session_id",
    "read_registry",
    "registry_path",
    "write_registry",
]
