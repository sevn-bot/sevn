"""Telegram inline answerInlineQuery tests (I3.1-I3.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.channels.telegram_capabilities import RichCapability
from sevn.config.sections.channels import TelegramInlineConfig
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.telegram.telegram_inline import (
    INLINE_BOTFATHER_SETUP_NOTE,
    build_answer_inline_query_payload,
    build_inline_dispatch_context,
    build_inline_input_message_content,
    compute_inline_answer_cache_time,
    dedupe_inline_results,
    dispatch_telegram_inline_query,
    handle_chosen_inline_result_feedback,
    is_inline_botfather_setup_error,
    maybe_emit_botfather_inline_warning,
    paginate_inline_results,
    sanitize_inline_results_for_api,
    try_route_telegram_inline,
    upgrade_inline_results_for_capability,
)
from sevn.gateway.telegram.telegram_inline_sources import inline_article_result
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


def _router(
    tmp_path: Path, conn: sqlite3.Connection, *, trace: TraceSink | None = None
) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "channels": {
                "telegram": {
                    "inline": {"enabled": True, "feedback": True},
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
        trace=trace or _CaptureTrace(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
        owner_user_ids=frozenset({"owner"}),
    )


def test_build_answer_inline_query_payload_shape() -> None:
    body = build_answer_inline_query_payload(
        inline_query_id="iq-99",
        results=[{"type": "article", "id": "1", "title": "t"}],
        cache_time=10,
        is_personal=True,
        next_offset="5",
    )
    assert body["inline_query_id"] == "iq-99"
    assert body["is_personal"] is True
    assert body["cache_time"] == 10
    assert body["next_offset"] == "5"
    assert len(body["results"]) == 1


def test_dedupe_inline_results_by_fingerprint() -> None:
    a = inline_article_result(result_id="1", title="Same", description="d", message_text="a")
    b = inline_article_result(result_id="2", title="Same", description="d", message_text="b")
    merged = dedupe_inline_results([a, b])
    assert len(merged) == 1


def test_paginate_inline_results_next_offset() -> None:
    rows = [
        inline_article_result(result_id=str(i), title=f"t{i}", description="", message_text="x")
        for i in range(5)
    ]
    page, nxt = paginate_inline_results(rows, offset="2", page_size=2)
    assert len(page) == 2
    assert page[0]["id"] == "2"
    assert nxt == "4"


def test_compute_inline_answer_cache_time_agent_vs_static() -> None:
    agent_row = inline_article_result(
        result_id="agent:0:abc",
        title="a",
        description="",
        message_text="x",
    )
    static_row = inline_article_result(
        result_id="second_brain:0:abc",
        title="b",
        description="",
        message_text="y",
    )
    assert (
        compute_inline_answer_cache_time([agent_row], cache_time_agent=10, cache_time_static=300)
        == 10
    )
    assert (
        compute_inline_answer_cache_time([static_row], cache_time_agent=10, cache_time_static=300)
        == 300
    )


def test_build_inline_input_message_content_html_when_not_capable() -> None:
    imc = build_inline_input_message_content("<b>x</b>", rich_capable=False)
    assert imc["parse_mode"] == "HTML"
    assert "rich_message" not in imc


def test_build_inline_input_message_content_rich_when_capable() -> None:
    imc = build_inline_input_message_content(
        "<b>x</b>",
        rich_capable=True,
        markdown_source="**x**",
    )
    assert "rich_message" in imc
    assert imc["rich_message"] == {"markdown": "**x**"}


def test_upgrade_inline_results_for_capability() -> None:
    row = inline_article_result(
        result_id="1",
        title="t",
        description="d",
        message_text="<b>x</b>",
        markdown_source="| A |\\n|---|---|\\n| 1 |",
    )
    rich_rows = upgrade_inline_results_for_capability([row], rich_capable=True)
    assert "rich_message" in rich_rows[0]["input_message_content"]
    html_rows = upgrade_inline_results_for_capability([row], rich_capable=False)
    assert html_rows[0]["input_message_content"]["parse_mode"] == "HTML"


def test_sanitize_inline_results_strips_internal_keys() -> None:
    row = inline_article_result(
        result_id="1",
        title="t",
        description="d",
        message_text="x",
        markdown_source="plain",
    )
    cleaned = sanitize_inline_results_for_api([row])
    assert "_inline_markdown" not in cleaned[0]


def test_is_inline_botfather_setup_error() -> None:
    assert is_inline_botfather_setup_error(
        {"ok": False, "description": "Forbidden: bot can't be used in inline mode"},
    )
    assert not is_inline_botfather_setup_error({"ok": True})


@pytest.mark.asyncio
async def test_chosen_inline_feedback_emits_no_user_id(tmp_path: Path) -> None:
    conn = _memory_conn()
    trace = _CaptureTrace()
    router = _router(tmp_path, conn, trace=trace)
    msg = IncomingMessage(
        channel="telegram",
        user_id="42",
        text="secret query text",
        metadata={
            "is_chosen_inline_result": True,
            "inline_result_id": "agent:0:deadbeef",
        },
    )
    await handle_chosen_inline_result_feedback(router, msg, correlation_id="corr-1")
    ev = next(e for e in trace.events if e.kind == "gateway.telegram.inline.chosen_result")
    assert "user_id" not in ev.attrs
    assert ev.attrs.get("result_id") == "agent:0:deadbeef"
    assert ev.attrs.get("query_len") == len("secret query text")


@pytest.mark.asyncio
async def test_botfather_warning_emits_once(tmp_path: Path) -> None:
    conn = _memory_conn()
    trace = _CaptureTrace()
    router = _router(tmp_path, conn, trace=trace)
    err = {"ok": False, "description": "Forbidden: bot can't be used in inline mode"}
    await maybe_emit_botfather_inline_warning(router, err)
    await maybe_emit_botfather_inline_warning(router, err)
    kinds = [e.kind for e in trace.events]
    assert kinds.count("gateway.telegram.inline.botfather_setup") == 1
    ev = next(e for e in trace.events if e.kind == "gateway.telegram.inline.botfather_setup")
    assert INLINE_BOTFATHER_SETUP_NOTE in str(ev.attrs.get("note"))


@pytest.mark.asyncio
async def test_dispatch_inline_query_answers_with_rich_content(tmp_path: Path) -> None:
    conn = _memory_conn()
    trace = _CaptureTrace()
    router = _router(tmp_path, conn, trace=trace)

    adapter = MagicMock(spec=TelegramAdapter)
    adapter.name = "telegram"
    adapter.rich_capability = RichCapability.CAPABLE
    adapter.answer_inline_query = AsyncMock(return_value={"ok": True})

    async def _fake_build_all(ctx: Any, **kwargs: Any) -> tuple[Any, ...]:
        from sevn.gateway.telegram.telegram_inline_sources import InlineSourceResult

        row = inline_article_result(
            result_id="agent:0:abc",
            title="Table",
            description="d",
            message_text="<pre>| A |</pre>",
            markdown_source="| A |\n|---|---|\n| 1 |",
        )
        return (
            InlineSourceResult(source="agent", cache_time=10, results=(row,)),
            InlineSourceResult(source="second_brain", cache_time=300, results=()),
            InlineSourceResult(source="printing_press", cache_time=300, results=()),
            InlineSourceResult(source="artifacts", cache_time=300, results=()),
        )

    router.register_adapter(adapter)
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="table data",
        metadata={
            "is_inline_query": True,
            "inline_query_id": "iq-dispatch",
            "inline_offset": "",
            "__correlation_id": "corr-dispatch",
        },
    )
    dispatch_ctx = build_inline_dispatch_context(
        "owner",
        inline_cfg=TelegramInlineConfig(enabled=True),
        owner_ids=frozenset({"owner"}),
        allowed_users=[],
    )

    import sevn.gateway.telegram.telegram_inline as inline_mod

    original = inline_mod.build_all_inline_source_results
    inline_mod.build_all_inline_source_results = _fake_build_all  # type: ignore[assignment]
    try:
        response = await dispatch_telegram_inline_query(
            router,
            msg,
            inline_cfg=TelegramInlineConfig(enabled=True),
            dispatch_ctx=dispatch_ctx,
        )
    finally:
        inline_mod.build_all_inline_source_results = original

    assert response.get("ok") is True
    adapter.answer_inline_query.assert_awaited_once()
    _args, kwargs = adapter.answer_inline_query.await_args  # type: ignore[union-attr]
    assert kwargs["is_personal"] is True
    assert kwargs["cache_time"] == 10
    results = kwargs["results"]
    assert len(results) == 1
    imc = results[0]["input_message_content"]
    assert "rich_message" in imc
    assert imc["rich_message"] == {"markdown": "| A |\n|---|---|\n| 1 |"}

    answer_events = [e for e in trace.events if e.kind == "gateway.telegram.inline.answer"]
    assert answer_events
    assert answer_events[0].attrs.get("rich_capable") is True


@pytest.mark.asyncio
async def test_try_route_inline_query_calls_answer(tmp_path: Path) -> None:
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

    import sevn.gateway.telegram.telegram_inline as inline_mod

    async def _empty_sources(ctx: Any, **kwargs: Any) -> tuple[Any, ...]:
        from sevn.gateway.telegram.telegram_inline_sources import InlineSourceResult

        return tuple(
            InlineSourceResult(source=src, cache_time=300, results=())  # type: ignore[arg-type]
            for src in ("agent", "second_brain", "printing_press", "artifacts")
        )

    original = inline_mod.build_all_inline_source_results
    inline_mod.build_all_inline_source_results = _empty_sources  # type: ignore[assignment]
    router.register_adapter(adapter)
    try:
        msg = IncomingMessage(
            channel="telegram",
            user_id="owner",
            text="hello",
            metadata={
                "is_inline_query": True,
                "inline_query_id": "iq-route",
                "__correlation_id": "corr-route",
            },
        )
        handled = await try_route_telegram_inline(router, msg)
    finally:
        inline_mod.build_all_inline_source_results = original

    assert handled is True
    adapter.answer_inline_query.assert_awaited_once()  # type: ignore[attr-defined]
    statuses = [e.status for e in trace.events if e.kind == "gateway.telegram.inline.answer"]
    assert "sending" in statuses
    assert "ok" in statuses


def test_smoke_post_split_telegram_inline_dispatch_import() -> None:
    """W6: inline dispatch submodule importable after router split."""
    import importlib

    importlib.import_module("sevn.gateway.telegram.telegram_inline_dispatch")
