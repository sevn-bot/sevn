"""Short-lived sessions against the host database."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sevn.paths import Paths
from sevn.store.db import async_engine


@asynccontextmanager
async def open_session() -> AsyncGenerator[AsyncSession]:
    engine = async_engine(f"sqlite+aiosqlite:///{Paths.from_env().db}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
