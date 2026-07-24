"""RED suite for Telegram outbound routing identity (D6, D7; green after W5)."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest

from sevn.gateway.queue.queue_multi import MultiDispatchHooks, MultiSpawnOutcome
from sevn.gateway.session_manager import SessionManager, dispatch_routing_for
from sevn.storage.migrate import apply_migrations

if TYPE_CHECKING:
    from loguru import Record


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _capture_loguru(*, level: str) -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Record) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


async def test_enqueue_dispatch_rejects_missing_chat_id() -> None:
    """D6: missing Telegram identity fails loudly at enqueue — not at send."""
    from sevn.gateway.session_manager import validate_dispatch_routing_identity

    with pytest.raises(ValueError, match="chat_id"):
        validate_dispatch_routing_identity(
            channel="telegram",
            chat_id=None,
            scope_key="telegram:4242",
        )


async def test_queued_dispatch_carries_chat_id_to_outbound_send() -> None:
    """D6: steer/queued jobs carry ``chat_id`` through to ``telegram_outbound.send``."""

    async def noop(_sid: str, _cid: str) -> None:
        return None

    sessions = SessionManager(_memory_conn())
    try:
        await sessions.enqueue_dispatch(
            "sess-1",
            correlation_id="corr-1",
            queue_mode="steer",
            dispatch=noop,
            channel="telegram",
            chat_id=4242,
        )
        routing = dispatch_routing_for(session_id="sess-1", correlation_id="corr-1")
        assert routing["chat_id"] == 4242
        assert routing["channel"] == "telegram"
    finally:
        await sessions.drain()


@pytest.mark.asyncio
async def test_classifier_timeout_preserves_chat_id_for_outbound_send() -> None:
    """D7: classifier-timeout spawn preserves ``chat_id`` via production dispatch routing."""
    started = asyncio.Event()
    release = asyncio.Event()
    notices: list[str] = []

    async def busy_dispatch(_sid: str, _cid: str) -> None:
        started.set()
        await release.wait()

    async def classify_busy(
        _in_flight: str,
        _queued: tuple[str, ...],
        _new: str,
    ) -> tuple[str, bool]:
        return "new_task", True

    async def spawn(_sid: str, _cid: str) -> MultiSpawnOutcome:
        return MultiSpawnOutcome.SPAWNED

    async def notify(_sid: str, line: str) -> None:
        notices.append(line)

    hooks = MultiDispatchHooks(
        classify_busy=classify_busy,
        spawn_new_task=spawn,
        notify_operator=notify,
    )
    sessions = SessionManager(_memory_conn())
    try:
        await sessions.enqueue_dispatch(
            "sess-d7",
            correlation_id="corr-busy",
            queue_mode="steer",
            dispatch=busy_dispatch,
            channel="telegram",
            chat_id=1001,
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await sessions.enqueue_dispatch(
            "sess-d7",
            correlation_id="corr-fallback",
            queue_mode="multi",
            dispatch=busy_dispatch,
            multi_hooks=hooks,
            new_message_text="follow-up",
            channel="telegram",
            chat_id=1001,
        )
        routing = dispatch_routing_for("sess-d7", "corr-fallback")
        assert routing["chat_id"] == 1001
        assert routing["channel"] == "telegram"
        assert routing.get("relatedness_classifier_fallback") is True
        assert any("timed out" in n.lower() for n in notices)
    finally:
        release.set()
        await sessions.drain()


def test_classifier_timeout_uses_production_dispatch_routing() -> None:
    """PR #52: drive ``_record_dispatch_routing`` + ``_merge_dispatch_routing_extras``."""
    from sevn.gateway.session_manager import (
        _merge_dispatch_routing_extras,
        _record_dispatch_routing,
    )

    _record_dispatch_routing("sess-d7-helpers", "corr-d7", channel="telegram", chat_id=1001)
    _merge_dispatch_routing_extras(
        "sess-d7-helpers",
        "corr-d7",
        {"relatedness_classifier_fallback": True},
    )
    routing = dispatch_routing_for("sess-d7-helpers", "corr-d7")
    assert routing["chat_id"] == 1001
    assert routing["channel"] == "telegram"
    assert routing.get("relatedness_classifier_fallback") is True


@pytest.mark.asyncio
async def test_send_without_chat_id_still_warns_today() -> None:
    """Baseline guard: missing ``chat_id`` at send time is still visible until W5 lands."""
    import httpx
    from loguru import logger as loguru_logger

    from sevn.channels.telegram import TelegramAdapter, TelegramConfig
    from sevn.gateway.channel_router import OutgoingMessage

    warnings, sink_id = _capture_loguru(level="WARNING")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="42",
                text="orphan",
                session_id="sess-missing",
                metadata={},
            ),
        )
    loguru_logger.remove(sink_id)
    assert out == []
    assert any("telegram_send_missing_chat_id" in line for line in warnings)
