"""Gateway restart acknowledgment persistence (`gateway_restart_ack`)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.gateway.gateway_restart_ack import (
    _filter_snapshot_lines,
    _message_content_is_menu_noise,
    clear_pending_gateway_restarts,
    deliver_pending_gateway_restart_acks,
    load_pending_gateway_restarts,
    mark_restart_ack_delivered,
    recent_restart_ack_delivered,
    record_pending_gateway_restart,
    restart_ack_delivered_path,
)


def test_record_and_load_pending_restart(tmp_path: Path) -> None:
    """Pending restart rows round-trip through the JSON marker file."""
    dot = tmp_path / ".sevn"
    dot.mkdir()
    record_pending_gateway_restart(
        dot,
        service="gateway",
        channel="telegram",
        user_id="owner1",
        chat_id=42,
        message_id=99,
        topic_id=None,
        session_id="sess-abc",
        conversation_snapshot=("user: hello", "assistant: hi"),
    )
    rows = load_pending_gateway_restarts(dot)
    assert len(rows) == 1
    assert rows[0].service == "gateway"
    assert rows[0].session_id == "sess-abc"
    assert rows[0].conversation_snapshot == ("user: hello", "assistant: hi")
    clear_pending_gateway_restarts(dot)
    assert load_pending_gateway_restarts(dot) == ()


def test_record_replaces_prior_pending_row(tmp_path: Path) -> None:
    """Repeated record calls keep a single pending row (no append storm)."""
    dot = tmp_path / ".sevn"
    dot.mkdir()
    for _ in range(4):
        record_pending_gateway_restart(
            dot,
            service="gateway",
            channel="telegram",
            user_id="owner1",
            chat_id=42,
            message_id=99,
            topic_id=None,
            session_id="sess-abc",
            conversation_snapshot=("user: act:gateway:restart:confirm",),
        )
    rows = load_pending_gateway_restarts(dot)
    assert len(rows) == 1
    assert rows[0].conversation_snapshot == ()


def test_snapshot_filters_menu_noise() -> None:
    """Menu callbacks and slash commands are omitted from restart snapshots."""
    assert _message_content_is_menu_noise("act:gateway:restart:confirm")
    assert _message_content_is_menu_noise("/config")
    filtered = _filter_snapshot_lines(
        ("user: act:gateway:restart:confirm", "user: salut", "user: /config"),
    )
    assert filtered == ("user: salut",)
    assert _message_content_is_menu_noise("Gateway restarted (proxy restarted too when installed).")


def test_recent_restart_ack_delivered_cooldown(tmp_path: Path) -> None:
    """Delivered-ack marker suppresses duplicate confirms within the cooldown window."""
    dot = tmp_path / ".sevn"
    dot.mkdir()
    assert recent_restart_ack_delivered(dot, 42) is False
    mark_restart_ack_delivered(dot, chat_id=42, user_id="owner1")
    assert restart_ack_delivered_path(dot).is_file()
    assert recent_restart_ack_delivered(dot, 42) is True
    assert recent_restart_ack_delivered(dot, 99) is False


@pytest.mark.asyncio
async def test_deliver_only_once_after_claim(tmp_path: Path) -> None:
    """Second deliver call is a no-op after the marker file is claimed."""
    dot = tmp_path / ".sevn"
    dot.mkdir()
    record_pending_gateway_restart(
        dot,
        service="gateway",
        channel="telegram",
        user_id="owner1",
        chat_id=42,
        message_id=99,
        topic_id=None,
        session_id="sess-abc",
        conversation_snapshot=(),
    )

    class _Adapter:
        def __init__(self) -> None:
            self.send = AsyncMock(return_value=["m1"])

    class _Router:
        def __init__(self) -> None:
            self._adapters = {"telegram": _Adapter()}

    router = _Router()
    first = await deliver_pending_gateway_restart_acks(
        router=router,  # type: ignore[arg-type]
        dot_sevn=dot,
    )
    second = await deliver_pending_gateway_restart_acks(
        router=router,  # type: ignore[arg-type]
        dot_sevn=dot,
    )
    assert first == 1
    assert second == 0
    telegram = router._adapters["telegram"]
    assert telegram.send.await_count == 1


@pytest.mark.asyncio
async def test_deliver_pending_sends_telegram_ack(tmp_path: Path) -> None:
    """Boot delivery posts one confirmation and clears the marker file."""
    dot = tmp_path / ".sevn"
    dot.mkdir()
    record_pending_gateway_restart(
        dot,
        service="gateway",
        channel="telegram",
        user_id="owner1",
        chat_id=42,
        message_id=99,
        topic_id=None,
        session_id="sess-abc",
        conversation_snapshot=(),
    )

    class _Adapter:
        def __init__(self) -> None:
            self.send = AsyncMock(return_value=["m1"])

    class _Router:
        def __init__(self) -> None:
            self._adapters = {"telegram": _Adapter()}

    router = _Router()
    count = await deliver_pending_gateway_restart_acks(
        router=router,  # type: ignore[arg-type]
        dot_sevn=dot,
        deployment_id="dep-test",
    )
    assert count == 1
    telegram = router._adapters["telegram"]
    telegram.send.assert_awaited_once()
    sent = telegram.send.await_args.args[0]
    assert sent.metadata.get("chat_id") == 42
    assert "Gateway restarted" in sent.text
    assert "dep-test" in sent.text
    assert load_pending_gateway_restarts(dot) == ()
    assert recent_restart_ack_delivered(dot, 42) is True
