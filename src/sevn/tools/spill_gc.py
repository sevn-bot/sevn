"""Best-effort cleanup for ``.sevn/tool_results/`` trees (`specs/11-tools-registry.md` §3.1).

Couples with gateway SQLite session rows: subdirectories named after ``session_id`` values
that are absent from ``gateway_sessions`` are removed. Invoked from gateway lifespan/cron
alongside other retention passes.

Module: sevn.tools.spill_gc
Depends: pathlib, shutil, sqlite3

Exports:
    prune_orphan_tool_result_dirs — delete stale per-session spill trees.

Examples:
    >>> import sqlite3
    >>> from pathlib import Path
    >>> from sevn.tools.spill_gc import prune_orphan_tool_result_dirs
    >>> conn = sqlite3.connect(":memory:")
    >>> _ = conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
    >>> _ = conn.execute("INSERT INTO gateway_sessions (session_id) VALUES ('active')")
    >>> root = Path("/nonexistent-sevn-spill-test")
    >>> prune_orphan_tool_result_dirs(content_root=root, conn=conn)
    0
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path


def prune_orphan_tool_result_dirs(*, content_root: Path, conn: sqlite3.Connection) -> int:
    """Remove ``tool_results/<session_id>/`` trees with no matching ``gateway_sessions`` row.

    Args:
        content_root (Path): Workspace content root (parent of ``.sevn``).
        conn (sqlite3.Connection): Open gateway SQLite handle (``gateway_sessions`` table).

    Returns:
        int: Count of session directories removed.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.tools.spill_gc import prune_orphan_tool_result_dirs
        >>> conn = sqlite3.connect(":memory:")
        >>> _ = conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
        >>> prune_orphan_tool_result_dirs(content_root=Path("/tmp/__missing__"), conn=conn)
        0
    """

    spill_root = content_root / ".sevn" / "tool_results"
    if not spill_root.is_dir():
        return 0

    rows = conn.execute("SELECT session_id FROM gateway_sessions").fetchall()
    keep = {str(r[0]) for r in rows if r and r[0] is not None}
    removed = 0
    try:
        for child in spill_root.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name in keep:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    except OSError:
        return removed
    return removed
