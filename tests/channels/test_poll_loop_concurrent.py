"""W2.2: the Telegram poll loop must not serialize on a slow ``handle_webhook``.

Previously each update was dispatched with ``await router.handle_webhook(...)``
directly in the poll loop, so one slow turn blocked reading/dispatching the next
update (`specs/17-gateway.md` §4.3, plan D9/W2). The loop now dispatches each
update as a bounded background task; per-session ordering is preserved
downstream by the per-session dispatch queue.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig


@pytest.mark.asyncio
async def test_slow_webhook_does_not_block_next_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow ``handle_webhook`` for update #1 does not delay update #2."""
    cfg = TelegramConfig(bot_token="poll-concurrent-token", mode="poll")
    adapter = TelegramAdapter(config=cfg, http_client=MagicMock())

    first_started = asyncio.Event()
    first_release = asyncio.Event()
    second_started = asyncio.Event()
    order: list[str] = []

    async def handle_webhook(_channel: str, upd: dict[str, Any]) -> None:
        uid = upd.get("update_id")
        if uid == 1:
            order.append("first_start")
            first_started.set()
            await first_release.wait()
            order.append("first_end")
        else:
            order.append("second_start")
            second_started.set()

    router = MagicMock()
    router.handle_webhook = handle_webhook
    adapter._router = router

    async def fake_api(method: str, body: dict[str, Any]) -> dict[str, Any]:
        _ = body
        assert method == "getUpdates"
        # Single batch with two updates, then stop the loop.
        adapter._stop.set()
        return {
            "ok": True,
            "result": [
                {"update_id": 1, "message": {"text": "slow"}},
                {"update_id": 2, "message": {"text": "fast"}},
            ],
        }

    async def noop_trace(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(adapter, "_api", fake_api)
    monkeypatch.setattr(adapter, "_drain_pending", _noop_coro)
    monkeypatch.setattr(adapter, "_ensure_client", _client_coro)
    monkeypatch.setattr(adapter, "_emit_trace", noop_trace)
    monkeypatch.setattr(adapter, "_flush_set_my_commands", _noop_coro)

    try:
        await adapter._poll_loop()
        # The second update's handler must run while the first is still blocked.
        await asyncio.wait_for(second_started.wait(), timeout=2.0)
        assert first_started.is_set()
        assert "first_end" not in order  # first is still blocked
        assert "second_start" in order
        # Offset still advanced past both updates.
        assert adapter._last_update_id == 2
    finally:
        first_release.set()
        await adapter.stop()


async def _noop_coro(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _client_coro(*_args: Any, **_kwargs: Any) -> object:
    return object()
