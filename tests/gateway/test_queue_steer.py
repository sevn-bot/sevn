"""Queue / steer / cancel integration (`specs/17-gateway.md` Wave 6)."""

from __future__ import annotations

import asyncio
import sqlite3
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
    return ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=run_turn,
        queue_mode=queue_mode,
    )


@pytest.fixture
def allow_scan(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.asyncio
async def test_cancel_aborts_in_flight_dispatch(tmp_path: Path, allow_scan: None) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        started.set()
        await release.wait()

    conn = _memory_conn()
    router = _router(tmp_path, conn, queue_mode="cancel", run_turn=slow_run)
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="u", text="a")),
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await router.route_incoming(IncomingMessage(channel="webchat", user_id="u", text="b"))
        release.set()
        await t1
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("webchat:u",),
        ).fetchone()
        assert row is not None
        sid = str(row[0])
        tail = unanswered_tail_message_id(conn, sid)
        last_user = conn.execute(
            "SELECT id FROM gateway_messages WHERE session_id = ? AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        assert last_user is not None
        assert tail == int(last_user[0])
    finally:
        release.set()
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_steer_queues_while_dispatch_running(tmp_path: Path, allow_scan: None) -> None:
    gate = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.2)

    conn = _memory_conn()
    router = _router(tmp_path, conn, queue_mode="steer", run_turn=slow_run)
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="s", text="one")),
        )
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        t2 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="s", text="two")),
        )
        await asyncio.sleep(0.02)
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("webchat:s",),
        ).fetchone()
        assert row is not None
        depth, running = router.session_manager.dispatch_queue_snapshot(str(row[0]))
        assert running is True
        assert depth >= 1
        await asyncio.gather(t1, t2)
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_steer_logs_queue_token_when_second_dispatch_queues(
    tmp_path: Path,
    allow_scan: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TE-2: ``gateway.queue_steer_queued`` INFO log surfaces when steer queues a second turn."""
    from loguru import logger as loguru_logger

    gate = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.2)

    conn = _memory_conn()
    router = _router(tmp_path, conn, queue_mode="steer", run_turn=slow_run)
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="INFO")
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="lg", text="one")),
        )
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        t2 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="lg", text="two")),
        )
        await asyncio.sleep(0.02)
        assert any("gateway.queue_steer_queued" in line for line in captured)
        assert any("depth=" in line for line in captured if "queue_steer_queued" in line)
        await asyncio.gather(t1, t2)
    finally:
        loguru_logger.remove(sink_id)
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_cancel_mode_does_not_emit_steer_log_token(
    tmp_path: Path,
    allow_scan: None,
) -> None:
    """``cancel`` mode never emits the steer/queue log token (regression guard)."""
    from loguru import logger as loguru_logger

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        started.set()
        await release.wait()

    conn = _memory_conn()
    router = _router(tmp_path, conn, queue_mode="cancel", run_turn=slow_run)
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="INFO")
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="lc", text="a")),
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await router.route_incoming(IncomingMessage(channel="webchat", user_id="lc", text="b"))
        release.set()
        await t1
        assert not any("gateway.queue_steer_queued" in line for line in captured)
    finally:
        release.set()
        loguru_logger.remove(sink_id)
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_attachment_data_base64_persisted(tmp_path: Path, allow_scan: None) -> None:
    conn = _memory_conn()

    async def noop_run(_sid: str, _cid: str) -> None:
        return None

    router = _router(tmp_path, conn, queue_mode="cancel", run_turn=noop_run)
    try:
        await router.route_incoming(
            IncomingMessage(
                channel="webchat",
                user_id="att",
                text="with file",
                attachments=[{"filename": "clip.txt", "data_base64": "Y2xpcA=="}],
            ),
        )
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("webchat:att",),
        ).fetchone()
        assert row is not None
        sid = str(row[0])
        path = tmp_path / "w" / "channel_files" / sid / "clip.txt"
        assert path.is_file()
        assert path.read_bytes() == b"clip"
        user_rows = conn.execute(
            "SELECT content FROM gateway_messages WHERE session_id = ? AND role = 'user'",
            (sid,),
        ).fetchall()
        assert any("with file" in str(r[0]) for r in user_rows)
        await router.session_manager.drain()
    finally:
        conn.close()
