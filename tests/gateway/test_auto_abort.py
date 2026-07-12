"""Per-session dispatch queue + cancel semantics (`specs/17-gateway.md` §4.3, §10.2)."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import (
    GatewayConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager, unanswered_tail_message_id
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router(
    tmp_path: Path,
    conn: sqlite3.Connection,
    *,
    queue_mode: str,
    run_turn: Any,
) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway=GatewayConfig(queue_mode=queue_mode, token="${SECRET:keychain:sevn.gateway.token}"),  # type: ignore[arg-type]
    )
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
    scanner = LLMGuardScanner(root, ws)
    return ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=scanner,
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
        run_turn=run_turn,
        queue_mode=queue_mode,
    )


@pytest.mark.asyncio
async def test_steer_two_rapid_inbounds_one_queued_one_running(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)

    gate = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.2)

    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router(tmp_path, conn, queue_mode="steer", run_turn=slow_run)
        m1 = IncomingMessage(channel="telegram", user_id="u1", text="a")
        t1 = asyncio.create_task(router.route_incoming(m1))
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        m2 = IncomingMessage(channel="telegram", user_id="u1", text="b")
        t2 = asyncio.create_task(router.route_incoming(m2))
        await asyncio.sleep(0.02)
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("telegram:u1",),
        ).fetchone()
        assert row is not None
        sid = str(row[0])
        depth, running = router.session_manager.dispatch_queue_snapshot(sid)
        assert running is True
        assert depth >= 1
        await asyncio.gather(t1, t2)
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_cancel_unanswered_tail_advances(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)

    async def slow_run(_sid: str, _cid: str) -> None:
        await asyncio.sleep(0.15)

    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router(tmp_path, conn, queue_mode="cancel", run_turn=slow_run)
        await router.route_incoming(IncomingMessage(channel="telegram", user_id="u2", text="first"))
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="u2", text="second")
        )
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("telegram:u2",),
        ).fetchone()
        assert row is not None
        sid = str(row[0])
        last_user = conn.execute(
            "SELECT id FROM gateway_messages WHERE session_id = ? AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        assert last_user is not None
        tail = unanswered_tail_message_id(conn, sid)
        assert tail == int(last_user[0])
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_different_sessions_run_in_parallel(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)

    async def slow_run(_sid: str, _cid: str) -> None:
        await asyncio.sleep(0.25)

    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router(tmp_path, conn, queue_mode="steer", run_turn=slow_run)
        m1 = IncomingMessage(
            channel="telegram",
            user_id="a1",
            text="x",
            metadata={"session_scope_override": "scope-a"},
        )
        m2 = IncomingMessage(
            channel="telegram",
            user_id="a2",
            text="y",
            metadata={"session_scope_override": "scope-b"},
        )
        t0 = time.perf_counter()
        await asyncio.gather(router.route_incoming(m1), router.route_incoming(m2))
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.4
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()
