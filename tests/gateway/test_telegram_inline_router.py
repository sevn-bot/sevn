"""Telegram inline mode plumbing tests (I1.1-I1.6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink, TraceEvent, TraceSink
from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.config.sections.channels import TelegramInlineConfig
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.telegram_inline import (
    build_inline_dispatch_context,
    inline_user_may_use_agent_source,
    telegram_allowed_updates,
    try_route_telegram_inline,
)
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations


class _CaptureTrace(TraceSink):
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _inline_payload(
    *, update_id: int = 1, user_id: int = 42, query: str = "weather"
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "inline_query": {
            "id": "iq-1",
            "from": {"id": user_id, "first_name": "Alice"},
            "query": query,
            "offset": "10",
        },
    }


def _chosen_payload(*, update_id: int = 2, user_id: int = 42) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "chosen_inline_result": {
            "result_id": "res-9",
            "from": {"id": user_id},
            "query": "weather",
        },
    }


def test_telegram_allowed_updates_inline_disabled() -> None:
    assert telegram_allowed_updates(None) == ["message", "edited_message", "callback_query"]
    assert telegram_allowed_updates(TelegramInlineConfig(enabled=False)) == [
        "message",
        "edited_message",
        "callback_query",
    ]


def test_telegram_allowed_updates_inline_enabled() -> None:
    assert telegram_allowed_updates(TelegramInlineConfig(enabled=True, feedback=False)) == [
        "message",
        "edited_message",
        "callback_query",
        "inline_query",
    ]


def test_telegram_allowed_updates_feedback_adds_chosen_inline_result() -> None:
    updates = telegram_allowed_updates(TelegramInlineConfig(enabled=True, feedback=True))
    assert "inline_query" in updates
    assert "chosen_inline_result" in updates


def test_adapter_allowed_updates_follows_config() -> None:
    off = TelegramAdapter(
        config=TelegramConfig(bot_token="tok", inline=TelegramInlineConfig(enabled=False)),
    )
    on = TelegramAdapter(
        config=TelegramConfig(
            bot_token="tok",
            inline=TelegramInlineConfig(enabled=True, feedback=True),
        ),
    )
    assert "inline_query" not in off._allowed_updates()
    assert "inline_query" in on._allowed_updates()
    assert "chosen_inline_result" in on._allowed_updates()


def test_parse_inline_query_typed_fields() -> None:
    adapter = TelegramAdapter(
        config=TelegramConfig(
            bot_token="tok",
            inline=TelegramInlineConfig(enabled=True),
        ),
    )
    msg = adapter.parse_webhook(_inline_payload(user_id=99, query="recipe pasta"))
    assert msg is not None
    assert msg.user_id == "99"
    assert msg.text == "recipe pasta"
    assert msg.metadata["is_inline_query"] is True
    assert msg.metadata["inline_query_id"] == "iq-1"
    assert msg.metadata["inline_offset"] == "10"


def test_parse_inline_query_ignored_when_disabled() -> None:
    adapter = TelegramAdapter(
        config=TelegramConfig(
            bot_token="tok",
            inline=TelegramInlineConfig(enabled=False),
        ),
    )
    assert adapter.parse_webhook(_inline_payload()) is None


def test_parse_chosen_inline_result_when_feedback_enabled() -> None:
    adapter = TelegramAdapter(
        config=TelegramConfig(
            bot_token="tok",
            inline=TelegramInlineConfig(enabled=True, feedback=True),
        ),
    )
    msg = adapter.parse_webhook(_chosen_payload(user_id=55))
    assert msg is not None
    assert msg.metadata["is_chosen_inline_result"] is True
    assert msg.metadata["inline_result_id"] == "res-9"
    assert msg.user_id == "55"


def test_parse_chosen_inline_result_ignored_without_feedback() -> None:
    adapter = TelegramAdapter(
        config=TelegramConfig(
            bot_token="tok",
            inline=TelegramInlineConfig(enabled=True, feedback=False),
        ),
    )
    assert adapter.parse_webhook(_chosen_payload()) is None


def test_agent_source_auth_owner_and_allowlist() -> None:
    assert inline_user_may_use_agent_source("1", owner_ids=frozenset({"1"}), allowed_users=[])
    assert inline_user_may_use_agent_source("2", owner_ids=frozenset(), allowed_users=[2])
    assert not inline_user_may_use_agent_source("9", owner_ids=frozenset({"1"}), allowed_users=[2])


def test_build_inline_dispatch_context_agent_gate() -> None:
    owner_ctx = build_inline_dispatch_context(
        "1",
        inline_cfg=TelegramInlineConfig(enabled=True),
        owner_ids=frozenset({"1"}),
        allowed_users=[],
    )
    assert owner_ctx.auth.agent_source_allowed is True
    assert owner_ctx.auth.is_personal is True

    stranger_ctx = build_inline_dispatch_context(
        "99",
        inline_cfg=TelegramInlineConfig(enabled=True),
        owner_ids=frozenset({"1"}),
        allowed_users=[2],
    )
    assert stranger_ctx.auth.agent_source_allowed is False


def _router(
    tmp_path: Path,
    conn: sqlite3.Connection,
    *,
    allowed_users: list[int] | None = None,
    trace: TraceSink | None = None,
) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "channels": {
                "telegram": {
                    "inline": {"enabled": True, "feedback": True},
                    "allowed_users": allowed_users or [],
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    return ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=trace or NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
        owner_user_ids=frozenset({"owner"}),
    )


@pytest.mark.asyncio
async def test_try_route_inline_query_emits_auth_attrs(tmp_path: Path) -> None:
    conn = _memory_conn()
    trace = _CaptureTrace()
    router = _router(tmp_path, conn, allowed_users=[7], trace=trace)
    msg = IncomingMessage(
        channel="telegram",
        user_id="99",
        text="hello",
        metadata={
            "is_inline_query": True,
            "inline_query_id": "iq-1",
            "__correlation_id": "corr-1",
        },
    )
    handled = await try_route_telegram_inline(router, msg)
    assert handled is True
    kinds = [e.kind for e in trace.events]
    assert "gateway.telegram.inline.query" in kinds
    inline_ev = next(e for e in trace.events if e.kind == "gateway.telegram.inline.query")
    assert inline_ev.attrs.get("agent_source_allowed") is False
    assert inline_ev.attrs.get("is_personal") is True


@pytest.mark.asyncio
async def test_try_route_inline_query_owner_gets_agent_source(tmp_path: Path) -> None:
    conn = _memory_conn()
    trace = _CaptureTrace()
    router = _router(tmp_path, conn, trace=trace)
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="hello",
        metadata={
            "is_inline_query": True,
            "inline_query_id": "iq-2",
            "__correlation_id": "corr-2",
        },
    )
    assert await try_route_telegram_inline(router, msg) is True
    inline_ev = next(e for e in trace.events if e.kind == "gateway.telegram.inline.query")
    assert inline_ev.attrs.get("agent_source_allowed") is True


@pytest.mark.asyncio
async def test_route_incoming_inline_does_not_persist_turn(tmp_path: Path) -> None:
    conn = _memory_conn()
    trace = _CaptureTrace()
    router = _router(tmp_path, conn, trace=trace)
    adapter = TelegramAdapter(
        config=TelegramConfig(
            bot_token="tok",
            inline=TelegramInlineConfig(enabled=True),
        ),
    )
    adapter.answer_inline_query = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]

    import sevn.gateway.telegram_inline as inline_mod

    async def _empty_sources(ctx: Any, **kwargs: Any) -> tuple[Any, ...]:
        from sevn.gateway.telegram_inline_sources import InlineSourceResult

        return tuple(
            InlineSourceResult(source=src, cache_time=300, results=())  # type: ignore[arg-type]
            for src in ("agent", "second_brain", "printing_press", "artifacts")
        )

    original = inline_mod.build_all_inline_source_results
    inline_mod.build_all_inline_source_results = _empty_sources  # type: ignore[assignment]
    router.register_adapter(adapter)
    try:
        body = _inline_payload(user_id=42)
        await router.handle_webhook("telegram", body)
    finally:
        inline_mod.build_all_inline_source_results = original
    statuses = [e.status for e in trace.events if e.kind == "gateway.route_incoming"]
    assert "inline_dispatched" in statuses
    row = conn.execute("SELECT COUNT(*) FROM gateway_messages").fetchone()
    assert row is not None
    assert row[0] == 0
    adapter.answer_inline_query.assert_awaited_once()  # type: ignore[attr-defined]


def test_smoke_post_split_telegram_inline_types_import() -> None:
    """W6: shared inline types module importable after router split."""
    import importlib

    importlib.import_module("sevn.gateway.telegram_inline_types")
