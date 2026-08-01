"""Browser profile persistence helpers — session markers, ephemeral mode, auth reset.

Module: sevn.browser.persistence
Depends: json, pathlib, shutil, sqlite3, sevn.browser.chrome, sevn.browser.registry

Exports:
    persist_browser_session_marker — write a JSON session marker under a profile dir.
    read_browser_session_marker — read a persisted session marker.
    resolve_browser_profile_dir — persistent or ephemeral Chrome profile path.
    clear_browser_auth_state — operator reset for saved browser auth artefacts.

Examples:
    >>> from pathlib import Path
    >>> import tempfile
    >>> root = Path(tempfile.mkdtemp())
    >>> from sevn.browser.persistence import resolve_browser_profile_dir
    >>> resolve_browser_profile_dir(root, "s1", ephemeral=True).parent.name
    'browser-ephemeral'
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.browser.chrome import resolve_profile_dir
from sevn.browser.registry import normalise_session_id

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_SESSION_MARKER: str = ".sevn-browser-session.json"


def persist_browser_session_marker(profile_dir: Path, marker: dict[str, Any]) -> None:
    """Persist a JSON session marker inside ``profile_dir``.

    Args:
        profile_dir (Path): Chrome ``user-data-dir``.
        marker (dict[str, Any]): JSON-serializable session metadata (no secrets).

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp())
        >>> persist_browser_session_marker(p, {"site": "example.com"})
        >>> (p / ".sevn-browser-session.json").is_file()
        True
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / _SESSION_MARKER
    path.write_text(json.dumps(marker, indent=2), encoding="utf-8")


def read_browser_session_marker(profile_dir: Path) -> dict[str, Any] | None:
    """Read the JSON session marker from ``profile_dir`` when present.

    Args:
        profile_dir (Path): Chrome ``user-data-dir``.

    Returns:
        dict[str, Any] | None: Parsed marker or ``None`` when missing/invalid.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp())
        >>> read_browser_session_marker(p) is None
        True
    """
    path = profile_dir / _SESSION_MARKER
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def resolve_browser_profile_dir(
    content_root: Path,
    session_id: str,
    cfg: WorkspaceConfig | None = None,
    *,
    ephemeral: bool = False,
) -> Path:
    """Resolve the Chrome profile directory for a gateway session.

    When ``ephemeral`` is ``True``, returns a workspace-local directory under
    ``.sevn/browser-ephemeral/`` that is outside the persistent
    ``browser-profiles`` tree (for sensitive one-off tasks).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Optional workspace config overrides.
        ephemeral (bool): When ``True``, use a non-persistent profile path.

    Returns:
        Path: Absolute profile directory (may not exist yet).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> persistent = resolve_browser_profile_dir(root, "s1")
        >>> ephemeral = resolve_browser_profile_dir(root, "s1", ephemeral=True)
        >>> persistent.parent.name
        'browser-profiles'
        >>> ephemeral.parent.name
        'browser-ephemeral'
    """
    if ephemeral:
        sid = normalise_session_id(session_id)
        base = (content_root / ".sevn" / "browser-ephemeral").resolve()
        base.mkdir(parents=True, exist_ok=True)
        return (base / sid).resolve()
    return resolve_profile_dir(content_root, session_id, cfg=cfg)


def _remove_tree(path: Path, removed: list[str]) -> None:
    """Remove ``path`` (file or directory) and append its string form to ``removed``.

    Args:
        path (Path): File or directory to delete.
        removed (list[str]): Accumulator for deleted paths.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp())
        >>> removed: list[str] = []
        >>> _remove_tree(p, removed)
        >>> p.exists()
        False
    """
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        removed.append(str(path))
    elif path.is_file():
        path.unlink(missing_ok=True)
        removed.append(str(path))


def clear_browser_auth_state(
    content_root: Path,
    cfg: WorkspaceConfig | None = None,
    *,
    session_id: str | None = None,
    include_configured_profile: bool = False,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Clear saved browser auth state (profiles, registries, session markers).

    Closes active sevn-spawned browsers first, then removes profile trees and
    registry JSON files. When ``session_id`` is set, only that session's artefacts
    are removed; otherwise all workspace browser profiles are cleared.

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config (for configured profile dir).
        session_id (str | None): Optional single-session scope.
        include_configured_profile (bool): When ``True``, also remove
            ``skills.browser.profile_dir`` when explicitly configured.
        conn (sqlite3.Connection | None): Optional SQLite handle for browser close.

    Returns:
        dict[str, Any]: Summary with ``removed`` path list and ``sessions_closed`` count.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> out = clear_browser_auth_state(Path(tempfile.mkdtemp()))
        >>> out["sessions_closed"] >= 0
        True
    """
    from sevn.browser.chrome import resolve_profile_dir
    from sevn.browser.registry import clear_registry
    from sevn.skills.browser_session import close_all_gateway_browsers, close_browser_session

    removed: list[str] = []
    sessions_closed = 0
    db = conn or sqlite3.connect(":memory:")
    own_conn = conn is None
    try:
        if session_id:
            sid = normalise_session_id(session_id)
            result = close_browser_session(content_root, sid)
            if result.ok:
                sessions_closed += 1
            profile = resolve_profile_dir(content_root, sid, cfg=cfg)
            _remove_tree(profile, removed)
            marker = profile / _SESSION_MARKER
            if marker.is_file():
                marker.unlink(missing_ok=True)
                removed.append(str(marker))
            reg = content_root / ".sevn" / "browser-sessions" / f"{sid}.json"
            if reg.is_file():
                reg.unlink(missing_ok=True)
                removed.append(str(reg))
            clear_registry(content_root, sid)
        else:
            sessions_closed = close_all_gateway_browsers(content_root=content_root, conn=db)
            profiles_root = content_root / ".sevn" / "browser-profiles"
            if profiles_root.is_dir():
                for child in list(profiles_root.iterdir()):
                    if child.is_dir():
                        _remove_tree(child, removed)
            ephemeral_root = content_root / ".sevn" / "browser-ephemeral"
            if ephemeral_root.is_dir():
                for child in list(ephemeral_root.iterdir()):
                    if child.is_dir():
                        _remove_tree(child, removed)
            sessions_root = content_root / ".sevn" / "browser-sessions"
            if sessions_root.is_dir():
                for child in list(sessions_root.glob("*.json")):
                    sid = child.stem
                    clear_registry(content_root, sid)
                    _remove_tree(child, removed)
    finally:
        if own_conn:
            db.close()

    if include_configured_profile and cfg is not None:
        from sevn.config.sections.accessors import browser_settings

        configured = browser_settings(cfg).profile_dir
        if configured:
            configured_path = Path(configured).expanduser().resolve()
            _remove_tree(configured_path, removed)

    return {"removed": removed, "sessions_closed": sessions_closed, "session_id": session_id}


__all__ = [
    "clear_browser_auth_state",
    "persist_browser_session_marker",
    "read_browser_session_marker",
    "resolve_browser_profile_dir",
]
