"""Workspace persistence — SQLite paths, connections, migrations.

Module: sevn.storage

Exports:
    MIGRATION_HEAD_VERSION — latest migration bundled with this binary.
    MigrationError — failed migration.
    StorageError — base storage error.
    apply_migrations — idempotent migration runner.
    connect_sqlite — opened DB with WAL + foreign keys.
    open_sevn_sqlite — ``sevn.db`` + migrate.
    sevn_db_path — ``.sevn/sevn.db`` path helper.
    traces_sqlite_path — ``.sevn/traces.db`` path helper.

Examples:
    >>> from sevn.storage import MIGRATION_HEAD_VERSION, sevn_db_path
    >>> from pathlib import Path
    >>> sevn_db_path(Path("/x/.sevn")).name
    'sevn.db'
    >>> MIGRATION_HEAD_VERSION >= 1
    True
"""

from __future__ import annotations

from sevn.storage.errors import MigrationError, StorageError
from sevn.storage.migrate import MIGRATION_HEAD_VERSION, apply_migrations
from sevn.storage.paths import sevn_db_path, traces_sqlite_path
from sevn.storage.sqlite import connect_sqlite, open_sevn_sqlite

__all__ = [
    "MIGRATION_HEAD_VERSION",
    "MigrationError",
    "StorageError",
    "apply_migrations",
    "connect_sqlite",
    "open_sevn_sqlite",
    "sevn_db_path",
    "traces_sqlite_path",
]
