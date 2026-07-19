"""RED suite for rich-capability probe log noise (D11; green after W8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.channels.telegram_capabilities import RichCapability, detect_rich_support

if TYPE_CHECKING:
    from loguru import Record


def _capture_loguru(*, level: str) -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Record) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


@pytest.mark.asyncio
async def test_rich_probe_chat_not_found_logs_debug_not_warning() -> None:
    """D11: expected ``sendRichMessage`` probe 400 logs at DEBUG — not WARNING."""
    from loguru import logger as loguru_logger

    warnings, warn_sink = _capture_loguru(level="WARNING")
    debug, debug_sink = _capture_loguru(level="DEBUG")

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.split("/")[-1]
        if method == "getMe":
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "b"}},
            )
        return httpx.Response(
            400,
            json={"ok": False, "description": "Bad Request: chat not found"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        assert await adapter._probe_rich_capability(force=True) is RichCapability.CAPABLE

    try:
        assert not any("chat not found" in line.lower() for line in warnings)
        assert any("chat not found" in line.lower() for line in debug)
    finally:
        loguru_logger.remove(warn_sink)
        loguru_logger.remove(debug_sink)


@pytest.mark.asyncio
async def test_detect_rich_support_still_treats_chat_not_found_as_capable() -> None:
    """D11 guard: capability detection semantics stay unchanged."""

    async def api_call(method: str, params: dict[str, object]) -> dict[str, object]:
        _ = params
        if method == "getMe":
            return {"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "b"}}
        return {"ok": False, "description": "Bad Request: chat not found"}

    assert await detect_rich_support(api_call) is RichCapability.CAPABLE
