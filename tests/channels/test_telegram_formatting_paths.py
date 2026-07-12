"""Characterization tests for Telegram outbound formatting delivery paths.

PATH MAP (D1/D2 invariants — ``specs/18`` §4.4, ``prd/01`` §5.4):

1. **Fresh send** — ``TelegramAdapter.send`` / ``_send_text`` → ``sendMessage``.
   Rich: ``body["text"] == to_telegram(original, parse_mode)`` (D1).
   Plain fallback: ``body["text"] == original``, no ``parse_mode`` (D2).

2. **Edit rich** — ``edit_message_text`` / ``_edit_message_text_body`` →
   ``editMessageText``. Same D1/D2 as path 1.

3. **Streaming** — ``TierBAnswerFinalizer.stream_update`` → ``adapter.edit_text``
   → ``edit_message_text`` → ``_edit_message_text_body`` (``turn_finalizer.py``).
   D1 on captured ``editMessageText`` body.

4. **Finalize edit** — ``adapter.send`` with ``metadata["edit_message_id"]`` →
   ``_send_text`` with ``edit_first`` → ``editMessageText``. D1 on rich attempt.

Gateway layers (``agent_turn``, ``turn_finalizer``) pass **raw** assistant text;
the adapter owns all formatting (D4).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sevn.channels.telegram import TelegramConfig
from sevn.channels.telegram_format import to_telegram
from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.turn_finalizer import TierBAnswerFinalizer
from tests.channels.test_markdown_safe import _MockTelegramAdapter

_PARSE_MODE = "HTML"

# ---------------------------------------------------------------------------
# Shared harness
# ---------------------------------------------------------------------------


class _FormattingPathAdapter(_MockTelegramAdapter):
    """Records every ``_api`` call for final Bot API body inspection (D6)."""

    def __init__(self, *, parse_mode: str = _PARSE_MODE) -> None:
        super().__init__()
        self._cfg = TelegramConfig(bot_token="test-token", parse_mode=parse_mode)  # type: ignore[arg-type]


class _EntityParseErrorAdapter(_FormattingPathAdapter):
    """Simulates rich→plain entity-parse 400 on the first ``parse_mode`` attempt."""

    async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        self.api_calls.append((method, dict(body)))
        if body.get("parse_mode"):
            return {"ok": False, "description": "can't parse entities at byte 12"}
        return {"ok": True, "result": {"message_id": 4242}}


class _StubRouter:
    async def route_outgoing(self, msg: Any) -> None:
        pass

    def cancel_telegram_typing(self, session_id: str) -> None:
        pass


def _last_api_body(adapter: _FormattingPathAdapter) -> dict[str, Any]:
    assert adapter.api_calls, "expected at least one _api call"
    return adapter.api_calls[-1][1]


def _rich_api_body(adapter: _FormattingPathAdapter) -> dict[str, Any]:
    rich_calls = [body for _, body in adapter.api_calls if body.get("parse_mode")]
    assert rich_calls, "expected a rich-mode _api call"
    return rich_calls[0]


# ---------------------------------------------------------------------------
# Payload fixtures (W3 matrix: 8 payloads)
# ---------------------------------------------------------------------------

_PAYLOADS: list[tuple[str, str]] = [
    ("plain_prose", "plain prose"),
    ("underscores", "a_b c_d"),
    ("parens", "(v1.2)"),
    ("bold", "**bold**"),
    ("code", "`code`"),
    ("fence", "```python\nx=1\n```"),
    ("link", "[link](https://x)"),
    ("pre_escaped", r"a\_b"),
]

_PATH_IDS = ("fresh_send", "edit_rich", "stream_update", "finalize_edit")


async def _invoke_fresh_send(adapter: _FormattingPathAdapter, text: str) -> None:
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter._send_text(
            chat_id=99,
            chunks=[text],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )


async def _invoke_edit_rich(adapter: _FormattingPathAdapter, text: str) -> None:
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter.edit_message_text(chat_id=99, message_id=42, text=text)


async def _invoke_stream_update(adapter: _FormattingPathAdapter, text: str) -> None:
    fin = TierBAnswerFinalizer(
        router=_StubRouter(),  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        channel="telegram",
        user_id="u",
        session_id="s",
        turn_id="t",
        metadata={"chat_id": 99},
    )
    fin._placeholder_message_id = "42"
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await fin.stream_update(text)


async def _invoke_finalize_edit(adapter: _FormattingPathAdapter, text: str) -> None:
    msg = OutgoingMessage(
        channel="telegram",
        user_id="u",
        text=text,
        metadata={"chat_id": 99, "edit_message_id": 42},
    )
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter.send(msg)


_PATH_INVOKERS: dict[str, Callable[[_FormattingPathAdapter, str], Awaitable[None]]] = {
    "fresh_send": _invoke_fresh_send,
    "edit_rich": _invoke_edit_rich,
    "stream_update": _invoke_stream_update,
    "finalize_edit": _invoke_finalize_edit,
}


# ---------------------------------------------------------------------------
# W3 — full 4x8 matrix (32 cases)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path_id", _PATH_IDS)
@pytest.mark.parametrize(("payload_id", "original"), _PAYLOADS, ids=[p[0] for p in _PAYLOADS])
async def test_delivery_path_rich_body_matches_converter(
    path_id: str,
    payload_id: str,
    original: str,
) -> None:
    """Every delivery path applies ``to_telegram`` exactly once on rich mode (D1)."""
    adapter = _FormattingPathAdapter()
    await _PATH_INVOKERS[path_id](adapter, original)
    body = _rich_api_body(adapter)
    assert body["text"] == to_telegram(original, _PARSE_MODE)
    assert body["parse_mode"] == _PARSE_MODE


# ---------------------------------------------------------------------------
# W2 — plain fallback (D2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_plain_fallback_rich_then_raw() -> None:
    """``_send_text`` rich attempt uses converter; plain retry sends raw original (D2)."""
    original = "edge **case**"
    adapter = _EntityParseErrorAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter._send_text(
            chat_id=7,
            chunks=[original],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )
    assert len(adapter.api_calls) == 2
    rich_body = adapter.api_calls[0][1]
    plain_body = adapter.api_calls[1][1]
    assert rich_body["parse_mode"] == _PARSE_MODE
    assert rich_body["text"] == to_telegram(original, _PARSE_MODE)
    assert "parse_mode" not in plain_body
    assert plain_body["text"] == original


@pytest.mark.asyncio
async def test_edit_plain_fallback_rich_then_raw() -> None:
    """``_edit_message_text_body`` plain retry sends raw original (D2)."""
    original = "edge **case**"
    adapter = _EntityParseErrorAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter.edit_message_text(chat_id=7, message_id=55, text=original)
    assert len(adapter.api_calls) == 2
    rich_body = adapter.api_calls[0][1]
    plain_body = adapter.api_calls[1][1]
    assert rich_body["parse_mode"] == _PARSE_MODE
    assert rich_body["text"] == to_telegram(original, _PARSE_MODE)
    assert "parse_mode" not in plain_body
    assert plain_body["text"] == original


# ---------------------------------------------------------------------------
# W2 — MarkdownV2 spot-check (D3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original",
    ["**bold**", "price is 1.50 (USD)!"],
    ids=["bold", "reserved_chars"],
)
async def test_fresh_send_markdownv2_body_matches_converter(original: str) -> None:
    """MarkdownV2 config applies ``to_telegram(..., 'MarkdownV2')`` on send (D3)."""
    adapter = _FormattingPathAdapter(parse_mode="MarkdownV2")
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter._send_text(
            chat_id=1,
            chunks=[original],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )
    body = _rich_api_body(adapter)
    assert body["parse_mode"] == "MarkdownV2"
    assert body["text"] == to_telegram(original, "MarkdownV2")


# ---------------------------------------------------------------------------
# W3 — pre-escaped input semantics (D7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_escaped_input_documents_converter_semantics() -> None:
    """Pre-escaped ``a\\_b`` is not idempotent through ``to_telegram`` (D7)."""
    original = r"a\_b"
    adapter = _FormattingPathAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter._send_text(
            chat_id=1,
            chunks=[original],
            thread_id=None,
            reply_to_int=None,
            disable_preview=True,
            reply_markup_first=None,
            edit_first=None,
        )
    body = _rich_api_body(adapter)
    expected = to_telegram(original, _PARSE_MODE)
    assert body["text"] == expected
    # D7: HTML converter passes ``a\_b`` through unchanged — unlike
    # ``escape_markdown_v2("a\\_b")`` which would double-escape.
    assert body["text"] == original
