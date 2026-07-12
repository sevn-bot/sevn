"""SQLite connection helpers for workspace databases.

Module: sevn.storage.sqlite

Exports:
    connect_sqlite — open with WAL + foreign keys, creating parent dirs.
    open_sevn_sqlite — open ``sevn.db`` and apply migrations.

Examples:
    >>> from pathlib import Path
    >>> from sevn.storage.sqlite import connect_sqlite
    >>> from sevn.storage.migrate import apply_migrations
    >>> conn = connect_sqlite(Path(":memory:"))
    >>> apply_migrations(conn) is None
    True
    >>> conn.execute("PRAGMA foreign_keys").fetchone()[0]
    1
    >>> conn.close()
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path


def connect_sqlite(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite database with sane pragmas for single-writer workloads.

        Args:
    db_path (Path): Target file; use ``Path(\":memory:\")`` for tests.

        Returns:
    sqlite3.Connection: Open connection; caller closes.

        Raises:
    OSError: If the parent directory cannot be created (file paths only).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.storage.sqlite import connect_sqlite
            >>> conn = connect_sqlite(Path(":memory:"))
            >>> conn.execute("PRAGMA foreign_keys").fetchone()[0]
            1
            >>> conn.close()
    """
    s = str(db_path)
    if s != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def open_sevn_sqlite(dot_sevn: Path) -> sqlite3.Connection:
    """Open the workspace ``sevn.db`` and bring schema to ``MIGRATION_HEAD_VERSION``.

        Args:
    dot_sevn (Path): Resolved ``WorkspaceLayout.dot_sevn``.

        Returns:
    sqlite3.Connection: Open connection after ``apply_migrations``.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.storage.sqlite import open_sevn_sqlite
            >>> root = Path(tempfile.mkdtemp())
            >>> dot = root / ".sevn"
            >>> dot.mkdir()
            >>> conn = open_sevn_sqlite(dot)
            >>> from sevn.storage.migrate import MIGRATION_HEAD_VERSION
            >>> int(conn.execute(
            ...     "SELECT MAX(version) FROM schema_migrations",
            ... ).fetchone()[0]) == MIGRATION_HEAD_VERSION
            True
            >>> conn.close()
    """
    conn = connect_sqlite(sevn_db_path(dot_sevn))
    apply_migrations(conn)
    return conn
