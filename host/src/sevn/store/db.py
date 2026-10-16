"""Async SQLite engine and programmatic Alembic upgrade."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


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
    from alembic.config import Config

    cfg = Config(str(_alembic_ini()))
    cfg.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    command.upgrade(cfg, "head")


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "alembic.ini"
