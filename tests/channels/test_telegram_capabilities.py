"""Tests for Bot API 10.1 rich-message capability detection (R1.1, D2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.channels.telegram_capabilities import RichCapability, detect_rich_support


def _getme_ok(*, supports_rich: bool | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"id": 1, "is_bot": True, "first_name": "bot"}
    if supports_rich is not None:
        result["supports_rich_messages"] = supports_rich
    return {"ok": True, "result": result}


@pytest.mark.asyncio
async def test_detect_rich_support_capable_via_sendrich_validation_error() -> None:
    async def api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "getMe":
            return _getme_ok()
        assert method == "sendRichMessage"
        return {"ok": False, "description": "Bad Request: chat not found"}

    assert await detect_rich_support(api_call) is RichCapability.CAPABLE


@pytest.mark.asyncio
async def test_detect_rich_support_not_capable_when_method_missing() -> None:
    async def api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "getMe":
            return _getme_ok()
        return {"ok": False, "error_code": 404, "description": "Not Found"}

    assert await detect_rich_support(api_call) is RichCapability.NOT_CAPABLE


@pytest.mark.asyncio
async def test_detect_rich_support_not_capable_when_rich_payload_rejected() -> None:
    # A "rich message must be non-empty" 400 means the server did not understand our
    # rich_message payload (schema mismatch) — degrade to legacy instead of 400ing
    # on every reply.
    async def api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "getMe":
            return _getme_ok()
        assert method == "sendRichMessage"
        return {"ok": False, "description": "Bad Request: rich message must be non-empty"}

    assert await detect_rich_support(api_call) is RichCapability.NOT_CAPABLE


@pytest.mark.asyncio
async def test_detect_rich_support_not_capable_when_getme_fails() -> None:
    async def api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "getMe":
            return {"ok": False, "description": "Unauthorized"}
        raise AssertionError("sendRichMessage must not run when getMe fails")

    assert await detect_rich_support(api_call) is RichCapability.NOT_CAPABLE


@pytest.mark.asyncio
async def test_detect_rich_support_not_capable_when_probe_raises() -> None:
    async def api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "getMe":
            return _getme_ok()
        raise RuntimeError("transport down")

    assert await detect_rich_support(api_call) is RichCapability.NOT_CAPABLE


@pytest.mark.asyncio
async def test_detect_rich_support_getme_flag_fast_path() -> None:
    async def api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "getMe"
        return _getme_ok(supports_rich=True)

    assert await detect_rich_support(api_call) is RichCapability.CAPABLE


@pytest.mark.asyncio
async def test_adapter_caches_rich_capability() -> None:
    adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"))
    adapter._api = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            _getme_ok(),
            {"ok": False, "description": "Bad Request: chat not found"},
        ]
    )
    first = await adapter._probe_rich_capability(force=True)
    second = await adapter._probe_rich_capability()
    assert first is RichCapability.CAPABLE
    assert second is RichCapability.CAPABLE
    assert adapter._api.await_count == 2


@pytest.mark.asyncio
async def test_adapter_reprobes_on_force_after_reconnect() -> None:
    adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"))
    adapter._api = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            _getme_ok(),
            {"ok": False, "error_code": 404, "description": "Not Found"},
            _getme_ok(),
            {"ok": False, "description": "Bad Request: chat not found"},
        ]
    )
    assert await adapter._probe_rich_capability(force=True) is RichCapability.NOT_CAPABLE
    assert await adapter._probe_rich_capability(force=True) is RichCapability.CAPABLE
    assert adapter._api.await_count == 4
