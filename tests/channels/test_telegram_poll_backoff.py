"""Telegram long-poll backoff and quiet connectivity logging (gateway recovery W6)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from loguru import logger as loguru_logger

from sevn.channels.telegram import (
    TelegramAdapter,
    TelegramConfig,
    _is_poll_connectivity_error,
    _poll_backoff_delay_s,
)


def _connect_error(message: str = "dns") -> httpx.ConnectError:
    request = httpx.Request("POST", "https://api.telegram.org/botx/getUpdates")
    return httpx.ConnectError(message, request=request)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_connect_error(), True),
        (httpx.ConnectTimeout("timeout", request=httpx.Request("GET", "https://x")), True),
        (RuntimeError("api logic"), False),
    ],
)
def test_is_poll_connectivity_error(exc: BaseException, expected: bool) -> None:
    assert _is_poll_connectivity_error(exc) is expected


def test_poll_backoff_delay_s_follows_schedule() -> None:
    assert _poll_backoff_delay_s(0) >= 1.0
    assert _poll_backoff_delay_s(1) >= 2.0
    assert _poll_backoff_delay_s(2) >= 5.0
    assert _poll_backoff_delay_s(3) >= 15.0
    assert _poll_backoff_delay_s(10) <= 30.0 + 30.0 * 0.25


@pytest.mark.asyncio
async def test_poll_loop_connectivity_backoff_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ConnectError yields one WARNING+traceback, growing backoff, then recovery INFO."""
    cfg = TelegramConfig(bot_token="poll-backoff-token", mode="poll")
    adapter = TelegramAdapter(config=cfg, http_client=MagicMock())
    adapter._router = MagicMock()
    adapter._router.handle_webhook = AsyncMock()

    api_calls = 0
    sleep_delays: list[float] = []
    log_lines: list[str] = []

    async def fake_api(method: str, body: dict[str, Any]) -> dict[str, Any]:
        nonlocal api_calls
        _ = body
        assert method == "getUpdates"
        api_calls += 1
        if api_calls <= 3:
            raise _connect_error("[Errno 8] nodename nor servname provided")
        # Successful poll after outage — stop the loop once recovery is handled.
        adapter._stop.set()
        return {"ok": True, "result": []}

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)
        assert adapter.connected is False

    async def noop_trace(**_kwargs: Any) -> None:
        return None

    sink_id = loguru_logger.add(
        lambda rec: log_lines.append(str(rec)),
        level="DEBUG",
    )
    monkeypatch.setattr(adapter, "_api", fake_api)
    monkeypatch.setattr(adapter, "_drain_pending", AsyncMock())
    monkeypatch.setattr(adapter, "_ensure_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(adapter, "_emit_trace", noop_trace)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    try:
        await adapter._poll_loop()
    finally:
        loguru_logger.remove(sink_id)

    assert api_calls == 4
    assert len(sleep_delays) == 3
    assert sleep_delays[0] >= 1.0
    assert sleep_delays[1] >= 2.0
    assert sleep_delays[2] >= 5.0

    offline_warnings = [line for line in log_lines if "telegram_poll_offline" in line]
    assert len(offline_warnings) == 1
    assert "WARNING" in offline_warnings[0]
    assert "api.telegram.org" in offline_warnings[0]
    assert not any("telegram_poll_iteration_failed" in line for line in log_lines)
    assert not any("ERROR" in line and "Logging error" not in line for line in log_lines)

    recovery = [line for line in log_lines if "telegram_poll_recovered" in line]
    assert len(recovery) == 1
    assert "INFO" in recovery[0]

    assert adapter.connected is True
