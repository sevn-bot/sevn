"""W2.1: ``enqueue_dispatch`` ``cancel`` mode must not block on the old turn.

Cancelling an in-flight dispatch used to ``await existing`` inside the serial
poll loop while holding the per-session enqueue lock, stalling the loop for the
entire old-turn unwind (`specs/17-gateway.md` §4.3, plan D9/W2). These tests
pin the non-blocking contract: ``enqueue_dispatch`` returns promptly and the
per-session worker reaps the ``CancelledError`` in the background.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


@pytest.mark.asyncio
async def test_cancel_mode_returns_without_awaiting_old_turn() -> None:
    """``enqueue_dispatch`` in ``cancel`` mode returns while the old turn is
    still unwinding; the worker observes the cancellation afterwards."""
    started = asyncio.Event()
    unwind_started = asyncio.Event()
    unwind_release = asyncio.Event()
    cancelled_observed = asyncio.Event()

    async def slow_dispatch(_sid: str, _cid: str) -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled_observed.set()
            # Simulate a slow ``finally`` unwind (e.g. aborting an LLM call).
            unwind_started.set()
            await unwind_release.wait()
            raise

    sessions = SessionManager(_memory_conn())
    sid = "sess-cancel"
    try:
        await sessions.enqueue_dispatch(
            sid,
            correlation_id="c1",
            queue_mode="cancel",
            dispatch=slow_dispatch,
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # The second cancel-mode enqueue must NOT block on the old turn unwind.
        loop = asyncio.get_running_loop()
        before = loop.time()
        await sessions.enqueue_dispatch(
            sid,
            correlation_id="c2",
            queue_mode="cancel",
            dispatch=slow_dispatch,
        )
        elapsed = loop.time() - before

        # Returned promptly even though the old turn is still mid-unwind.
        assert elapsed < 0.5
        assert not unwind_release.is_set()

        # The worker reaped the cancellation in the background.
        await asyncio.wait_for(cancelled_observed.wait(), timeout=2.0)
        await asyncio.wait_for(unwind_started.wait(), timeout=2.0)
    finally:
        unwind_release.set()
        await sessions.drain()
        sessions.connection.close()


@pytest.mark.asyncio
async def test_cancel_mode_drains_queue_and_runs_latest() -> None:
    """Cancel mode clears the queue and ultimately runs only the latest cid."""
    seen: list[str] = []
    first_started = asyncio.Event()
    release = asyncio.Event()

    async def dispatch(_sid: str, cid: str) -> None:
        seen.append(cid)
        if cid == "first":
            first_started.set()
            await release.wait()

    sessions = SessionManager(_memory_conn())
    sid = "sess-latest"
    try:
        await sessions.enqueue_dispatch(
            sid,
            correlation_id="first",
            queue_mode="cancel",
            dispatch=dispatch,
        )
        await asyncio.wait_for(first_started.wait(), timeout=2.0)
        depth_before, running_before = sessions.dispatch_queue_snapshot(sid)
        assert running_before is True
        assert depth_before == 0

        await sessions.enqueue_dispatch(
            sid,
            correlation_id="latest",
            queue_mode="cancel",
            dispatch=dispatch,
        )
        release.set()
        # Give the worker time to reap + run the latest cid.
        for _ in range(200):
            if "latest" in seen:
                break
            await asyncio.sleep(0.01)
        assert "latest" in seen
    finally:
        release.set()
        await sessions.drain()
        sessions.connection.close()
