"""Async SQLite engine and programmatic Alembic upgrade."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from alembic.config import Config


class _Cursor(Protocol):
    def execute(self, sql: str) -> object: ...

    def close(self) -> None: ...


class _DbapiConnection(Protocol):
    def cursor(self) -> _Cursor: ...


def utcnow() -> datetime:
    return datetime.now(UTC)


def apply_sqlite_pragmas(dbapi_connection: object) -> None:
    connection = cast("_DbapiConnection", dbapi_connection)
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def on_sqlite_connect(dbapi_connection: object, _connection_record: object) -> None:
    apply_sqlite_pragmas(dbapi_connection)


def async_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 5})
    event.listen(engine.sync_engine, "connect", on_sqlite_connect)
    return engine


def sync_url(url: str) -> str:
    return url.replace("sqlite+aiosqlite://", "sqlite://", 1)


async def upgrade(url: str) -> None:
    await asyncio.to_thread(_upgrade_sync, url)


def _upgrade_sync(url: str) -> None:
    from alembic import command

    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    command.upgrade(cfg, "head")


def _alembic_config() -> Config:
    from alembic.config import Config

    ini = _find_alembic_ini(Path(__file__).resolve())
    if ini is not None:
        return Config(str(ini))
    cfg = Config()
    cfg.set_main_option("script_location", str(_migrations_dir()))
    cfg.set_main_option("path_separator", "os")
    return cfg


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _find_alembic_ini(start: Path) -> Path | None:
    """Nearest alembic.ini above ``start``, or none in a wheel install."""
    for parent in start.resolve().parents:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    return None
