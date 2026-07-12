"""Unit tests for :mod:`sevn.runtime.background_tasks`."""

from __future__ import annotations

import asyncio

import pytest

from sevn.runtime.background_tasks import _HOLDERS, spawn_logged


@pytest.mark.asyncio
async def test_spawn_logged_happy_path_removes_holder() -> None:
    async def _noop() -> None:
        return None

    task = spawn_logged(_noop(), label="happy")
    assert task is not None
    assert task in _HOLDERS
    await task
    await asyncio.sleep(0)
    assert task not in _HOLDERS


@pytest.mark.asyncio
async def test_spawn_logged_raises_calls_on_error() -> None:
    calls: list[str] = []

    async def _boom() -> None:
        raise ValueError("boom")

    task = spawn_logged(_boom(), label="raise_me", on_error=calls.append)
    assert task is not None
    with pytest.raises(ValueError, match="boom"):
        await task
    await asyncio.sleep(0)
    assert calls == ["raise_me"]


@pytest.mark.asyncio
async def test_spawn_logged_cancelled_skips_on_error() -> None:
    calls: list[str] = []

    async def _slow() -> None:
        await asyncio.sleep(10)

    task = spawn_logged(_slow(), label="cancel_me", on_error=calls.append)
    assert task is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert calls == []


def test_spawn_logged_no_running_loop_returns_none() -> None:
    async def _noop() -> None:
        return None

    assert spawn_logged(_noop(), label="sync") is None
