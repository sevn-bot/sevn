"""W23.3 — transport errors must not leak bot tokens or secrets (#81 → W24)."""

from __future__ import annotations

import httpx
import pytest

from sevn.channels.telegram_api import TelegramApiMixin
from sevn.channels.telegram_config import TelegramConfig


class _TelegramProbe(TelegramApiMixin):
    """Minimal adapter stub exercising ``TelegramApiMixin._api`` transport errors."""

    def __init__(self, *, token: str, client: httpx.AsyncClient) -> None:
        self._cfg = TelegramConfig(bot_token=token)
        self._external_client = client


@pytest.mark.asyncio
async def test_telegram_transport_exception_never_contains_bot_token() -> None:
    """Re-raised httpx transport errors must not embed the bot token (#81)."""
    token = "1234567890:SUPER_SECRET_BOT_TOKEN_XYZ"

    def _fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "connection failed",
            request=httpx.Request("POST", f"https://api.telegram.org/bot{token}/sendMessage"),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(_fail))
    probe = _TelegramProbe(token=token, client=client)
    with pytest.raises(httpx.ConnectError) as exc_info:
        await probe._api("sendMessage", {"chat_id": 1, "text": "hi"})
    rendered = str(exc_info.value)
    assert token not in rendered, "transport error leaked bot token"


@pytest.mark.asyncio
async def test_telegram_api_error_log_line_redacts_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Structured send errors passed through ``redact_log_line`` before logging."""
    token = "987654321:LEAK_ME_NOT"
    probe = _TelegramProbe(token=token, client=httpx.AsyncClient())
    res = {
        "ok": False,
        "description": f"Unauthorized — bad token {token}",
        "error_code": 401,
    }
    probe._log_send_api_error("sendMessage", res)
    combined = " ".join(record.message for record in caplog.records)
    assert token not in combined
