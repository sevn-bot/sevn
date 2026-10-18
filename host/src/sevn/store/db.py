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


def _alembic_config(start: Path | None = None) -> Config:
    from alembic.config import Config

    origin = Path(__file__).resolve() if start is None else start
    ini = _find_alembic_ini(origin)
    if ini is not None:
        return Config(str(ini))
    cfg = Config()
    cfg.set_main_option("script_location", str(_migrations_dir()))
    cfg.set_main_option("path_separator", "os")
    return cfg


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _find_alembic_ini(start: Path) -> Path | None:
    """Nearest sevn alembic.ini above ``start``, or none when no owned ini exists."""
    migrations = _migrations_dir().resolve()
    for parent in start.resolve().parents:
        candidate = parent / "alembic.ini"
        if not candidate.is_file():
            continue
        if _resolved_script_location(candidate) == migrations:
            return candidate
    return None


def _resolved_script_location(ini: Path) -> Path | None:
    """Resolved ``script_location``, or none when the ini cannot be read as sevn's."""
    import configparser

    from alembic.config import Config
    from alembic.util.exc import CommandError

    try:
        location = Config(str(ini)).get_main_option("script_location")
    except (configparser.Error, CommandError, OSError, UnicodeError, ValueError):
        return None
    if location is None:
        return None
    return Path(location).resolve()
