"""Best-effort cleanup for session-scoped browser profiles and registries.

Couples with gateway SQLite session rows: ``.sevn/browser-profiles/<session_id>/``
trees and ``.sevn/browser-sessions/<session_id>.json`` files whose ``session_id``
is absent from ``gateway_sessions`` are removed. Invoked from gateway lifespan/cron
alongside other retention passes.

Module: sevn.skills.browser_gc
Depends: pathlib, shutil, sqlite3

Exports:
    prune_orphan_browser_profiles — delete stale per-session browser artefacts.

Examples:
    >>> import sqlite3
    >>> from pathlib import Path
    >>> from sevn.skills.browser_gc import prune_orphan_browser_profiles
    >>> conn = sqlite3.connect(":memory:")
    >>> _ = conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
    >>> _ = conn.execute("INSERT INTO gateway_sessions (session_id) VALUES ('active')")
    >>> root = Path("/nonexistent-sevn-browser-gc-test")
    >>> prune_orphan_browser_profiles(content_root=root, conn=conn)
    0
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path


def prune_orphan_browser_profiles(*, content_root: Path, conn: sqlite3.Connection) -> int:
    """Remove browser profile dirs and registry files with no ``gateway_sessions`` row.

    Args:
        content_root (Path): Workspace content root (parent of ``.sevn``).
        conn (sqlite3.Connection): Open gateway SQLite handle (``gateway_sessions`` table).

    Returns:
        int: Count of profile directories and registry files removed.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.skills.browser_gc import prune_orphan_browser_profiles
        >>> conn = sqlite3.connect(":memory:")
        >>> _ = conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
        >>> prune_orphan_browser_profiles(content_root=Path("/tmp/__missing__"), conn=conn)
        0
    """
    rows = conn.execute("SELECT session_id FROM gateway_sessions").fetchall()
    keep = {str(r[0]) for r in rows if r and r[0] is not None}
    removed = 0
    profiles_root = content_root / ".sevn" / "browser-profiles"
    sessions_root = content_root / ".sevn" / "browser-sessions"
    try:
        if profiles_root.is_dir():
            for child in profiles_root.iterdir():
                if not child.is_dir():
                    continue
                if child.name in keep:
                    continue
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        if sessions_root.is_dir():
            for child in sessions_root.iterdir():
                if not child.is_file() or child.suffix != ".json":
                    continue
                if child.stem in keep:
                    continue
                child.unlink(missing_ok=True)
                removed += 1
    except OSError:
        return removed
    return removed
