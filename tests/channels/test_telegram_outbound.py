"""RED suite for Telegram outbound routing identity (D6, D7; green after W5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from loguru import Record


def _capture_loguru(*, level: str) -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Record) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


@pytest.mark.xfail(reason="green after W5: chat_id captured at enqueue", strict=False)
async def test_enqueue_dispatch_rejects_missing_chat_id() -> None:
    """D6: missing Telegram identity fails loudly at enqueue — not at send."""
    from sevn.gateway.session_manager import validate_dispatch_routing_identity

    with pytest.raises(ValueError, match="chat_id"):
        validate_dispatch_routing_identity(channel="telegram", chat_id=None)


@pytest.mark.xfail(reason="green after W5: chat_id captured at enqueue", strict=False)
async def test_queued_dispatch_carries_chat_id_to_outbound_send() -> None:
    """D6: steer/queued jobs carry ``chat_id`` through to ``telegram_outbound.send``."""
    from sevn.gateway.session_manager import dispatch_routing_for

    routing = dispatch_routing_for(session_id="sess-1", correlation_id="corr-1")
    assert routing["chat_id"] == 4242
    assert routing["channel"] == "telegram"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W5: classifier timeout keeps routing context", strict=False)
async def test_classifier_timeout_preserves_chat_id_for_outbound_send() -> None:
    """D7: classifier timeout fallback must preserve ``chat_id``/channel routing context."""
    from sevn.agent.triager.relatedness import RelatednessResult, routing_context_from_relatedness

    result = RelatednessResult(label="new_task", fallback=True)
    ctx = routing_context_from_relatedness(
        result,
        chat_id=1001,
        channel="telegram",
    )
    assert ctx["chat_id"] == 1001
    assert ctx["channel"] == "telegram"


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
