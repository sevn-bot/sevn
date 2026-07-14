"""Telegram typing indicator loop (reactive-plum Wave 4)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.voice.tts import TextToSpeechPipeline


class _TypingAdapter:
    """Minimal telegram adapter stub recording chat actions."""

    name = "telegram"

    def __init__(self) -> None:
        self.send_chat_action = AsyncMock()

    def parse_webhook(self, payload: dict) -> None:  # type: ignore[type-arg]
        return None

    async def send(self, message: object) -> list[str]:
        _ = message
        return ["1"]


def _router(tmp_path: Path) -> ChannelRouter:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        tts_pipeline=TextToSpeechPipeline(
            (),
            voice_trigger_keywords=(),
            trace=NullTraceSink(),
            tts_output_dir=root / "tts",
        ),
    )
    router.register_adapter(_TypingAdapter())  # type: ignore[arg-type]
    return router


@pytest.mark.asyncio
async def test_typing_action_emitted_and_cancelled_on_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing fires immediately, reschedules, and stops when cancelled."""
    real_sleep = asyncio.sleep

    async def _fast_sleep(delay: float) -> None:
        await real_sleep(0.01 if delay >= 1 else delay)

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    router = _router(tmp_path)
    adapter = router._adapters["telegram"]
    assert isinstance(adapter, _TypingAdapter)

    msg = IncomingMessage(
        channel="telegram",
        user_id="42",
        text="hi",
        metadata={"chat_id": 100},
    )
    router._schedule_telegram_typing(msg, session_id="sess-typing")

    await asyncio.sleep(0.05)
    assert adapter.send_chat_action.await_count >= 1
    adapter.send_chat_action.reset_mock()

    router.cancel_telegram_typing("sess-typing")
    await asyncio.sleep(0.05)
    adapter.send_chat_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_typing_loop_swallows_transient_connect_errors_quietly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS/connect blips log at debug without multi-page tracebacks."""
    from loguru import logger as loguru_logger

    real_sleep = asyncio.sleep

    async def _fast_sleep(delay: float) -> None:
        await real_sleep(0.01 if delay >= 1 else delay)

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    router = _router(tmp_path)
    adapter = router._adapters["telegram"]
    assert isinstance(adapter, _TypingAdapter)
    adapter.send_chat_action = AsyncMock(
        side_effect=httpx.ConnectError(
            "nodename nor servname provided",
            request=httpx.Request("POST", "https://api.telegram.org/bot/x/sendChatAction"),
        )
    )

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        msg = IncomingMessage(
            channel="telegram",
            user_id="42",
            text="hi",
            metadata={"chat_id": 100},
        )
        router._schedule_telegram_typing(msg, session_id="sess-offline")
        await asyncio.sleep(0.05)
        router.cancel_telegram_typing("sess-offline")
    finally:
        loguru_logger.remove(sink_id)

    joined = "\n".join(captured)
    assert "telegram_typing_offline" in joined
    assert "telegram_typing_failed" not in joined
    assert "Traceback" not in joined
