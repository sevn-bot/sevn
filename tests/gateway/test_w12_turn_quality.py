"""Wave W12 — first-message dedupe, edit-noise, and ``(no output)`` persistence guards."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.gateway.agent_turn import _deliverable_assistant_text, _strip_preamble_echo
from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.telegram_quick_actions import build_quick_action_inline_keyboard
from sevn.gateway.turn_finalizer import TierBAnswerFinalizer
from sevn.prompts.fallbacks import ASSISTANT_NO_OUTPUT_PLACEHOLDER


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def test_deliverable_assistant_text_rejects_no_output_placeholder() -> None:
    assert _deliverable_assistant_text(ASSISTANT_NO_OUTPUT_PLACEHOLDER) is None
    assert _deliverable_assistant_text("  real answer  ") == "real answer"


def test_strip_preamble_echo_removes_triager_opener_before_body() -> None:
    opener = "On it — searching now."
    final = f"{opener}\n\nOsvaldo Pugliese was an Argentine pianist."
    assert _strip_preamble_echo(final, opener) == "Osvaldo Pugliese was an Argentine pianist."


@pytest.mark.asyncio
async def test_final_edit_skips_edit_message_text_when_streamed_body_unchanged() -> None:
    """W12.3: identical streamed+final bodies must not call ``editMessageText``."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "editMessageReplyMarkup":
            return _json_response({"ok": True, "result": {"message_id": 100}})
        return _json_response({"ok": True, "result": {"message_id": 100}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        adapter._last_edit_text[(42, 100)] = "streamed final body"
        kb = build_quick_action_inline_keyboard(100)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="streamed final body",
                session_id="s",
                metadata={
                    "chat_id": 42,
                    "edit_message_id": 100,
                    "inline_keyboard": kb,
                    "telegram_skip_text_edit": True,
                },
            ),
        )

    assert "editMessageText" not in calls
    assert "editMessageReplyMarkup" in calls
    assert out == ["100"]


class _StubAdapter:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, message: Any) -> list[str]:
        self.sent.append(message)
        return ["101"]

    async def edit_text(self, **_kwargs: Any) -> bool:
        return True


class _StubRouter:
    def __init__(self) -> None:
        self.outgoing: list[Any] = []

    async def route_outgoing(self, msg: Any) -> None:
        self.outgoing.append(msg)

    def cancel_telegram_typing(self, _session_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_finalizer_sets_skip_text_edit_when_stream_matches_final() -> None:
    adapter = _StubAdapter()
    router = _StubRouter()
    fin = TierBAnswerFinalizer(
        router=router,  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        channel="telegram",
        user_id="u",
        session_id="s",
        turn_id="t",
        metadata={"chat_id": 42},
    )
    await fin.place_placeholder()
    await fin.stream_update("Same streamed answer.")
    await fin.finalize(status="success", text="Same streamed answer.")
    assert router.outgoing
    md = router.outgoing[0].metadata
    assert md.get("telegram_skip_text_edit") is True
    assert md.get("gateway_outbound_phase") == "final"
