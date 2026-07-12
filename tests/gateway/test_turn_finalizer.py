"""Tests for ``TierBAnswerFinalizer`` (PROBLEMS.md Priority 2)."""

from __future__ import annotations

from typing import Any

import pytest

from sevn.gateway.turn_finalizer import TierBAnswerFinalizer


class _StubAdapter:
    """Channel adapter stub recording sends + edits."""

    def __init__(self, *, supports_edit: bool = True, send_ids: tuple[str, ...] = ("p1",)) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self._supports_edit = supports_edit
        self._send_ids = send_ids

    async def send(self, message: Any) -> list[str]:
        self.sent.append({"text": message.text, "metadata": dict(message.metadata)})
        return list(self._send_ids)

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        self.edits.append(
            {
                "channel_message_id": channel_message_id,
                "text": new_text,
                "metadata": dict(metadata or {}),
            },
        )
        return self._supports_edit


class _StubRouter:
    """Router stub: captures fallback sends."""

    def __init__(self) -> None:
        self.fallback_sends: list[dict[str, Any]] = []
        self.cancelled_typing: list[str] = []

    async def route_outgoing(self, msg: Any) -> None:
        self.fallback_sends.append({"text": msg.text, "metadata": dict(msg.metadata)})

    def cancel_telegram_typing(self, session_id: str) -> None:
        self.cancelled_typing.append(session_id)


def _make(adapter: _StubAdapter, router: _StubRouter | None = None) -> TierBAnswerFinalizer:
    return TierBAnswerFinalizer(
        router=router or _StubRouter(),  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        channel="telegram",
        user_id="u",
        session_id="s",
        turn_id="t",
        metadata={"chat_id": 42},
    )


@pytest.mark.asyncio
async def test_place_placeholder_captures_first_id() -> None:
    adapter = _StubAdapter(send_ids=("99",))
    fin = _make(adapter)
    pid = await fin.place_placeholder()
    assert pid == "99"
    assert fin.placeholder_message_id == "99"
    assert adapter.sent == [
        {
            "text": "…",
            "metadata": {
                "chat_id": 42,
                "telegram_streaming_active": True,
                "telegram_rich_draft": True,
            },
        },
    ]


@pytest.mark.asyncio
async def test_place_placeholder_falls_back_to_none_when_send_returns_empty() -> None:
    adapter = _StubAdapter(send_ids=())
    fin = _make(adapter)
    assert await fin.place_placeholder() is None
    assert fin.placeholder_message_id is None


@pytest.mark.asyncio
async def test_finalize_success_routes_through_router_with_edit_hint() -> None:
    """Success → router.route_outgoing with edit_message_id (Step 6 design).

    Reuses the router's quick-action markup attachment + assistant-row insert
    rather than reimplementing them in the finalizer.
    """
    adapter = _StubAdapter(send_ids=("101",))
    router = _StubRouter()
    fin = _make(adapter, router)
    await fin.place_placeholder()
    edited = await fin.finalize(status="success", text="Here's your answer.")
    assert edited is True
    # No direct adapter.edit_text call — the router handles the edit via
    # edit_message_id metadata.
    assert adapter.edits == []
    assert router.fallback_sends == [
        {
            "text": "Here's your answer.",
            "metadata": {
                "chat_id": 42,
                "edit_message_id": 101,
                "gateway_outbound_phase": "final",
            },
        }
    ]


@pytest.mark.asyncio
async def test_streamed_final_noop_still_routes_markup_phase() -> None:
    """P0#1: streamed text == final text → finalize still routes the markup phase.

    With real streaming back on, ``stream_update`` can push the exact final body to
    the placeholder, so ``finalize(success)`` is a no-op text edit. The finalizer
    must STILL route through the ``gateway_outbound_phase=final`` + ``edit_message_id``
    path (where the Telegram adapter attaches the 👍/👎/regen bar via a markup-only
    ``editMessageReplyMarkup`` on the 400 "message is not modified"). Dropping that
    route would reintroduce the missing-buttons bug.
    """
    adapter = _StubAdapter(send_ids=("202",))
    router = _StubRouter()
    fin = _make(adapter, router)
    await fin.place_placeholder()
    # Streaming pushed the exact final answer to the placeholder already.
    await fin.stream_update("The final answer, streamed in full.")
    edited = await fin.finalize(status="success", text="The final answer, streamed in full.")
    assert edited is True
    # Still routed through the markup-bearing phase=final path despite the no-op text.
    assert router.fallback_sends == [
        {
            "text": "The final answer, streamed in full.",
            "metadata": {
                "chat_id": 42,
                "edit_message_id": 202,
                "gateway_outbound_phase": "final",
                "telegram_skip_text_edit": True,
            },
        }
    ]


@pytest.mark.asyncio
async def test_finalize_timeout_uses_canned_fallback_text() -> None:
    adapter = _StubAdapter(supports_edit=True)
    fin = _make(adapter)
    await fin.place_placeholder()
    await fin.finalize(status="timeout")
    assert adapter.edits[0]["text"].startswith("I ran out of time")


@pytest.mark.asyncio
async def test_finalize_empty_status_uses_canned_text() -> None:
    adapter = _StubAdapter(supports_edit=True)
    fin = _make(adapter)
    await fin.place_placeholder()
    await fin.finalize(status="empty")
    assert "without producing a reply" in adapter.edits[0]["text"]


@pytest.mark.asyncio
async def test_finalize_cancellation_uses_switching_text() -> None:
    adapter = _StubAdapter(supports_edit=True)
    fin = _make(adapter)
    await fin.place_placeholder()
    await fin.finalize(status="cancelled")
    assert "previous request was dropped" in adapter.edits[0]["text"]


@pytest.mark.asyncio
async def test_finalize_failure_falls_back_to_send_when_adapter_returns_false() -> None:
    """For failure statuses, adapter declines the edit → router gets a fresh send.

    Failure paths still use adapter.edit_text directly (no quick-action markup
    needed on a terminal error message).
    """
    adapter = _StubAdapter(supports_edit=False)
    router = _StubRouter()
    fin = _make(adapter, router)
    await fin.place_placeholder()
    edited = await fin.finalize(status="timeout")
    assert edited is False
    assert len(adapter.edits) == 1
    assert router.fallback_sends
    assert "ran out of time" in router.fallback_sends[0]["text"]


@pytest.mark.asyncio
async def test_finalize_success_without_placeholder_routes_through_router() -> None:
    """If place_placeholder yielded no id, success still routes via the router.

    No edit_message_id is set since there's no placeholder to target.
    """
    adapter = _StubAdapter(send_ids=())
    router = _StubRouter()
    fin = _make(adapter, router)
    await fin.place_placeholder()
    edited = await fin.finalize(status="success", text="answer")
    assert edited is False
    assert adapter.edits == []
    assert router.fallback_sends == [{"text": "answer", "metadata": {"chat_id": 42}}]


@pytest.mark.asyncio
async def test_finalize_failure_falls_back_when_edit_raises() -> None:
    """If adapter.edit_text raises on a failure path, fall back to router send."""

    class _RaisingAdapter(_StubAdapter):
        async def edit_text(self, **_kwargs: Any) -> bool:
            raise RuntimeError("transport down")

    adapter = _RaisingAdapter()
    router = _StubRouter()
    fin = _make(adapter, router)
    await fin.place_placeholder()
    edited = await fin.finalize(status="error")
    assert edited is False
    assert router.fallback_sends
    assert router.fallback_sends[0]["text"].startswith("Sorry")


@pytest.mark.asyncio
async def test_double_finalize_raises() -> None:
    """Invariant: finalize runs exactly once per turn (`PROBLEMS.md` Priority 2 contract item 5)."""
    adapter = _StubAdapter()
    fin = _make(adapter)
    await fin.place_placeholder()
    await fin.finalize(status="success", text="answer")
    with pytest.raises(RuntimeError, match="already called"):
        await fin.finalize(status="success", text="another")


@pytest.mark.asyncio
async def test_is_finalized_flag_flips_after_call() -> None:
    adapter = _StubAdapter()
    fin = _make(adapter)
    await fin.place_placeholder()
    assert fin.is_finalized is False
    await fin.finalize(status="success", text="ok")
    assert fin.is_finalized is True
