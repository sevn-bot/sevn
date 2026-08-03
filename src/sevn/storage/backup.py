"""Online backup and restore helpers for workspace ``sevn.db``.

Module: sevn.storage.backup

Uses SQLite's online backup API after a WAL checkpoint so operators can
snapshot a consistent database without stopping the gateway.

Exports:
    backup_sevn_db — write a consistent copy to ``dest``.
    restore_sevn_db — replace ``sevn.db`` from a prior backup file.

Examples:
    >>> from pathlib import Path
    >>> import tempfile
    >>> from sevn.storage.backup import backup_sevn_db, restore_sevn_db
    >>> from sevn.storage.sqlite import connect_sqlite, open_sevn_sqlite
    >>> root = Path(tempfile.mkdtemp())
    >>> dot = root / ".sevn"
    >>> dot.mkdir()
    >>> conn = open_sevn_sqlite(dot)
    >>> conn.close()
    >>> dest = root / "backup.sqlite"
    >>> backup_sevn_db(dot / "sevn.db", dest)
    >>> restore_sevn_db(dest, dot / "sevn.db")
    True
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from sevn.storage.errors import StorageError
from sevn.storage.sqlite import connect_sqlite


def backup_sevn_db(source: Path, dest: Path) -> None:
    """Write a consistent copy of ``source`` to ``dest``.

    Checkpoints the WAL on ``source`` then uses ``Connection.backup``.

    Args:
        source (Path): Live ``sevn.db`` path.
        dest (Path): Output backup file (parent dirs created).

    Raises:
        StorageError: When ``source`` is missing or backup fails.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.storage.sqlite import open_sevn_sqlite
        >>> root = Path(tempfile.mkdtemp())
        >>> dot = root / ".sevn"
        >>> dot.mkdir()
        >>> conn = open_sevn_sqlite(dot)
        >>> conn.close()
        >>> backup_sevn_db(dot / "sevn.db", root / "snap.sqlite")
        >>> (root / "snap.sqlite").is_file()
        True
    """
    if not source.is_file():
        raise StorageError(f"database not found: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = connect_sqlite(source)
    try:
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src_conn.commit()
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()
    except sqlite3.Error as exc:
        raise StorageError(f"backup failed for {source}: {exc}") from exc
    finally:
        src_conn.close()


def restore_sevn_db(backup: Path, dest: Path) -> None:
    """Replace ``dest`` with ``backup`` and drop WAL sidecar files.

    Args:
        backup (Path): File produced by :func:`backup_sevn_db`.
        dest (Path): Target ``sevn.db`` path to overwrite.

    Raises:
        StorageError: When ``backup`` is missing.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.storage.sqlite import open_sevn_sqlite
        >>> root = Path(tempfile.mkdtemp())
        >>> dot = root / ".sevn"
        >>> dot.mkdir()
        >>> conn = open_sevn_sqlite(dot)
        >>> conn.close()
        >>> snap = root / "snap.sqlite"
        >>> backup_sevn_db(dot / "sevn.db", snap)
        >>> restore_sevn_db(snap, dot / "sevn.db")
        >>> dot.joinpath("sevn.db").is_file()
        True
    """
    if not backup.is_file():
        raise StorageError(f"backup not found: {backup}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        sidecar = dest.with_name(dest.name + suffix)
        if sidecar.is_file():
            sidecar.unlink()
    shutil.copy2(backup, dest)


__all__ = ["backup_sevn_db", "restore_sevn_db"]
