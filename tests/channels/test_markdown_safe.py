"""Tests for ``sevn.channels.markdown_safe`` (`PROBLEMS.md` §9 / Step §9)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sevn.channels.markdown_safe import (
    MARKDOWN_V2_RESERVED,
    escape_intent_footer,
    escape_markdown_v2,
)
from sevn.channels.telegram import TelegramAdapter, _markdown_escape


def test_reserved_charset_matches_telegram_spec() -> None:
    """The 18 chars per Telegram Bot API formatting-options §MarkdownV2."""
    assert frozenset("_*[]()~`>#+-=|{}.!") == MARKDOWN_V2_RESERVED
    assert len(MARKDOWN_V2_RESERVED) == 18


def test_escape_preserves_plain_ascii_words() -> None:
    """Untouched text is identity — no spurious backslashes."""
    assert escape_markdown_v2("hello world") == "hello world"
    assert escape_markdown_v2("intent NEW") == "intent NEW"


def test_escape_handles_all_18_reserved_chars() -> None:
    """Every reserved char is escaped exactly once."""
    for ch in MARKDOWN_V2_RESERVED:
        out = escape_markdown_v2(ch)
        assert out == f"\\{ch}", f"char {ch!r} produced {out!r}"


def test_escape_handles_backslash_explicitly() -> None:
    """Backslash itself is reserved so re-escape doubles it."""
    assert escape_markdown_v2("\\") == "\\\\"
    # And running twice produces *four* backslashes (no special idempotence).
    assert escape_markdown_v2(escape_markdown_v2("\\")) == "\\\\\\\\"


def test_escape_preserves_non_reserved_unicode() -> None:
    """U+00B7 middle dot (used in the intent footer) is NOT reserved."""
    assert escape_markdown_v2("intent · tier · conf") == "intent · tier · conf"
    assert escape_markdown_v2("emoji 🚀 here") == "emoji 🚀 here"


def test_escape_intent_footer_handles_real_footer_shape() -> None:
    """The real ``intent=NEW · tier=B · conf=0.95`` payload round-trips."""
    body = "intent=NEW_REQUEST · tier=B · conf=0.95"
    out = escape_intent_footer(body)
    # ``=`` and ``.`` and ``_`` are reserved; ``·`` is not.
    assert out == "intent\\=NEW\\_REQUEST · tier\\=B · conf\\=0\\.95"


def test_escape_empty_input_is_noop() -> None:
    assert escape_markdown_v2("") == ""
    assert escape_intent_footer("") == ""


def test_escape_mixed_sequence() -> None:
    """Adjacent reserved chars each get their own backslash."""
    assert escape_markdown_v2("**bold**") == "\\*\\*bold\\*\\*"
    assert escape_markdown_v2("a[b](c)") == "a\\[b\\]\\(c\\)"


def test_legacy_markdown_escape_alias_redirects() -> None:
    """``telegram._markdown_escape`` is now a thin alias for compat."""
    assert _markdown_escape("a_b") == escape_markdown_v2("a_b")
    assert _markdown_escape("intent=X") == escape_markdown_v2("intent=X")


# Mock-driven assertions on the adapter's send pipeline (telegram.py:1593-1614).


class _MockTelegramAdapter(TelegramAdapter):
    """Captures every ``_api`` call so we can inspect the parse_mode chain."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.api_calls: list[tuple[str, dict[str, Any]]] = []
        self.next_response: dict[str, Any] = {
            "ok": True,
            "result": {"message_id": 4242},
        }

    async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        self.api_calls.append((method, dict(body)))
        return dict(self.next_response)


@pytest.mark.asyncio
async def test_adapter_first_send_uses_configured_parse_mode_with_converter() -> None:
    """First send uses the configured ``parse_mode`` (default HTML) via the W9 converter — no legacy ``Markdown`` step."""
    adapter = _MockTelegramAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        out_ids = await adapter._send_text(
            chat_id=99,
            chunks=["intent=NEW · conf=0.95 & <ok>"],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )
    assert out_ids == ["4242"]
    assert len(adapter.api_calls) == 1  # one shot — no 400 retry round trip
    method, body = adapter.api_calls[0]
    assert method == "sendMessage"
    # Default parse_mode is HTML (Wave W9 / decision D5).
    assert body["parse_mode"] == "HTML"
    # HTML special chars are entity-escaped by the converter.
    assert body["text"] == "intent=NEW · conf=0.95 &amp; &lt;ok&gt;"


@pytest.mark.asyncio
async def test_adapter_falls_back_to_plain_on_400() -> None:
    """If the converted send returns ``ok=False``, the adapter retries with no parse_mode."""

    class _FailingFirstThenPlainAdapter(_MockTelegramAdapter):
        async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
            self.api_calls.append((method, dict(body)))
            if body.get("parse_mode"):
                return {"ok": False, "description": "can't parse entities"}
            return {"ok": True, "result": {"message_id": 99}}

    adapter = _FailingFirstThenPlainAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        out_ids = await adapter._send_text(
            chat_id=7,
            chunks=["edge case"],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )
    assert out_ids == ["99"]
    # Exactly two attempts: configured mode (HTML) then plain.
    assert [body.get("parse_mode") for _, body in adapter.api_calls] == ["HTML", None]


@pytest.mark.asyncio
async def test_adapter_never_uses_legacy_markdown_v1() -> None:
    """The legacy ``Markdown`` (v1) parse mode is never used — only the configured mode or plain."""

    class _ParseErrorAdapter(_MockTelegramAdapter):
        async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
            self.api_calls.append((method, dict(body)))
            # Return the only kind of 400 the adapter retries on.
            if body.get("parse_mode"):
                return {"ok": False, "description": "can't parse entities at byte 12"}
            return {"ok": True, "result": {"message_id": 99}}

    adapter = _ParseErrorAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter._send_text(
            chat_id=1,
            chunks=["x"],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )
    parse_modes = [body.get("parse_mode") for _, body in adapter.api_calls]
    # No legacy ``Markdown`` (v1) sent at any step.
    assert "Markdown" not in parse_modes
    assert parse_modes == ["HTML", None]
