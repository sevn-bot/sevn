"""``run_sync_coro`` loop-safe CLI helper."""

from __future__ import annotations

import asyncio

from sevn.cli.asyncio_util import run_sync_coro


async def _returns_value() -> str:
    return "ok"


def test_run_sync_coro_without_running_loop() -> None:
    assert run_sync_coro(_returns_value()) == "ok"


def test_run_sync_coro_with_running_loop() -> None:
    async def _inner() -> None:
        assert run_sync_coro(_returns_value()) == "ok"

    asyncio.run(_inner())
