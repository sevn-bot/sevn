"""Telegram poll-loop trace volume: transitions by default, ticks only on demand."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.channels.telegram_poll import _poll_cycle_tick_tracing_enabled


def _connect_error(message: str = "dns") -> httpx.ConnectError:
    request = httpx.Request("POST", "https://api.telegram.org/botx/getUpdates")
    return httpx.ConnectError(message, request=request)


async def _run_poll_loop_with_outage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outage_polls: int,
) -> list[dict[str, Any]]:
    """Drive ``_poll_loop`` through an outage and return the emitted trace events."""
    cfg = TelegramConfig(bot_token="poll-trace-token", mode="poll")
    adapter = TelegramAdapter(config=cfg, http_client=MagicMock())
    adapter._router = MagicMock()
    adapter._router.handle_webhook = AsyncMock()

    api_calls = 0
    emitted: list[dict[str, Any]] = []

    async def fake_api(method: str, body: dict[str, Any]) -> dict[str, Any]:
        nonlocal api_calls
        _ = body
        assert method == "getUpdates"
        api_calls += 1
        if api_calls <= outage_polls:
            raise _connect_error("[Errno 8] nodename nor servname provided")
        adapter._stop.set()
        return {"ok": True, "result": []}

    async def record_trace(**kwargs: Any) -> None:
        emitted.append(kwargs)

    async def fake_sleep(delay: float) -> None:
        _ = delay

    monkeypatch.setattr(adapter, "_api", fake_api)
    monkeypatch.setattr(adapter, "_drain_pending", AsyncMock())
    monkeypatch.setattr(adapter, "_ensure_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(adapter, "_probe_rich_capability", AsyncMock())
    monkeypatch.setattr(adapter, "_emit_trace", record_trace)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await adapter._poll_loop()
    return emitted


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("0", False), ("", False)],
)
def test_poll_cycle_tick_flag_parsing(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("SEVN_TRACE_POLL_CYCLE", value)
    assert _poll_cycle_tick_tracing_enabled() is expected


def test_poll_cycle_tick_flag_unset_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_TRACE_POLL_CYCLE", raising=False)
    assert _poll_cycle_tick_tracing_enabled() is False


@pytest.mark.asyncio
async def test_poll_loop_emits_transitions_not_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default posture: one span per outage and one per recovery, zero per-cycle ticks."""
    monkeypatch.delenv("SEVN_TRACE_POLL_CYCLE", raising=False)
    emitted = await _run_poll_loop_with_outage(monkeypatch, outage_polls=3)

    statuses = [event["status"] for event in emitted]
    assert statuses == ["offline", "recovered"]
    assert all(event["kind"] == "channel.telegram.poll.cycle" for event in emitted)
    # Three failed polls share a single offline span — the backoff loop can spin for
    # hours, and one span per retry is what made this the loudest kind in the export.
    assert statuses.count("offline") == 1


@pytest.mark.asyncio
async def test_poll_loop_offline_span_omits_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the exception type is traced — messages can embed the bot token URL."""
    monkeypatch.delenv("SEVN_TRACE_POLL_CYCLE", raising=False)
    emitted = await _run_poll_loop_with_outage(monkeypatch, outage_polls=1)

    offline = next(event for event in emitted if event["status"] == "offline")
    assert offline["attrs"]["error"] == "ConnectError"
    assert "nodename" not in str(offline["attrs"])


@pytest.mark.asyncio
async def test_poll_loop_tick_tracing_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SEVN_TRACE_POLL_CYCLE=1`` restores the per-iteration tick for loop debugging."""
    monkeypatch.setenv("SEVN_TRACE_POLL_CYCLE", "1")
    emitted = await _run_poll_loop_with_outage(monkeypatch, outage_polls=2)

    ticks = [event for event in emitted if event["status"] == "tick"]
    assert len(ticks) == 3
    assert all("offset" in event["attrs"] for event in ticks)
